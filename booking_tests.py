"""Control tests for the Bistro Uno booking agent. Each returns {"pass": bool, ...evidence}."""
import shutil
import tempfile
from pathlib import Path

import booking_agent as ba
from booking_agent import (BistroKit, BookingAgent, CHATS, FakeClock, ManagerDesk, PermissionDenied,
                           SimulatedCrash, build_context, Scratchpad, SeatingMemory)

RINA = next(c for c in CHATS if c["chat_id"] == "B04")      # party of 12, manager approves
MARCO = next(c for c in CHATS if c["chat_id"] == "B02")     # party of 4


def _setup(script=None, crash_after=None):
    d = Path(tempfile.mkdtemp(prefix="bk-test-"))
    kit, clock = BistroKit(), FakeClock()
    desk = ManagerDesk(script=script or {}, clock=clock)
    agent = BookingAgent(kit, desk, d / "runs", d / "mem.json", clock=clock, crash_after=crash_after)
    return d, kit, desk, agent, clock


def test_resume_after_deposit_saved():
    """Crash right after deposit_charged=true is written: resume must not charge again."""
    d, kit, desk, agent, _ = _setup({"B04": "approve"}, crash_after="deposit_saved")
    try:
        agent.run(RINA, resume=False)
    except SimulatedCrash:
        pass
    agent.crash_after = None
    r = agent.run(RINA, resume=True)
    out = {"pass": r["status"] == "booked" and len(kit.deposits) == 1 and kit.calls.count("charge_deposit") == 1
                   and len(desk.log) == 1,
           "charge_deposit calls": kit.calls.count("charge_deposit"), "deposits": len(kit.deposits),
           "manager asked": len(desk.log), "booking": r["booking_id"]}
    shutil.rmtree(d); return out


def test_resume_after_charge_before_write():
    """Crash after the payment succeeded but BEFORE the scratchpad write: the idempotency key saves us."""
    d, kit, desk, agent, _ = _setup({"B04": "approve"}, crash_after="charge_deposit")
    try:
        agent.run(RINA, resume=False)
    except SimulatedCrash:
        pass
    agent.crash_after = None
    r = agent.run(RINA, resume=True)
    out = {"pass": r["status"] == "booked" and len(kit.deposits) == 1 and len(desk.log) == 1,
           "charge_deposit calls": kit.calls.count("charge_deposit"), "deposits actually taken": len(kit.deposits),
           "receipt": r["deposit_receipt"]}
    shutil.rmtree(d); return out


def test_resume_booking_id_set_only_confirms():
    d, kit, desk, agent, _ = _setup(crash_after="booking_saved")
    try:
        agent.run(MARCO, resume=False)
    except SimulatedCrash:
        pass
    agent.crash_after = None
    before = len([b for b in kit.bookings.values() if b["phone"] == MARCO["phone"]])
    r = agent.run(MARCO, resume=True)
    after = len([b for b in kit.bookings.values() if b["phone"] == MARCO["phone"]])
    out = {"pass": after == 1 and r["status"] == "booked" and kit.calls.count("create_booking") == 1,
           "bookings for guest": after, "create_booking calls": kit.calls.count("create_booking"), "was": before}
    shutil.rmtree(d); return out


def test_retry_recovers():
    d, kit, desk, agent, clock = _setup()
    kit.fail_next["check_availability"] = 2
    t0 = clock.now()
    r = agent.run(MARCO, resume=False)
    out = {"pass": r["status"] == "booked", "backoff waited s": clock.now() - t0, "status": r["status"]}
    shutil.rmtree(d); return out


def test_no_retry_on_money():
    """Only transient reads are retried. A failed charge is never blindly retried."""
    d, kit, desk, agent, _ = _setup({"B04": "approve"})
    kit.fail_next["charge_deposit"] = 1
    r = agent.run(RINA, resume=False)
    out = {"pass": kit.calls.count("charge_deposit") == 1 and not r["deposit_charged"] and r["status"] == "handed_to_staff",
           "charge attempts": kit.calls.count("charge_deposit"), "status": r["status"]}
    shutil.rmtree(d); return out


def test_breaker_opens_and_falls_back():
    d, kit, desk, agent, clock = _setup()
    kit.always_fail.add("check_availability")
    chats = [dict(MARCO, chat_id=f"X{i}") for i in range(3)]
    r1 = agent.run(chats[0], resume=False)          # 3 failures
    r2 = agent.run(chats[1], resume=False)          # 2 more -> breaker opens at 5
    n_calls = kit.calls.count("check_availability")
    r3 = agent.run(chats[2], resume=False)          # fails fast, no call to the backend
    fast = kit.calls.count("check_availability") == n_calls
    kit.always_fail.clear(); clock.sleep(ba.BREAKER_COOLDOWN_S)
    r4 = agent.run(dict(MARCO, chat_id="X9"), resume=False)   # half-open probe succeeds
    out = {"pass": r1["status"] == r2["status"] == r3["status"] == "handed_to_staff" and fast and r4["status"] == "booked"
                   and not any(b["phone"] == MARCO["phone"] and b["booking_id"] != r4["booking_id"] for b in kit.bookings.values()),
           "failed fast while open": fast, "after cooldown": r4["status"]}
    shutil.rmtree(d); return out


def test_permission_scope():
    d, kit, desk, agent, _ = _setup()
    sp = Scratchpad.open(MARCO, d / "runs", resume=False)
    res = {}
    for tool in ("refund_deposit", "change_price", "lookup_any_booking"):
        try:
            agent.call(sp, tool); res[tool] = "ran"
        except PermissionDenied:
            res[tool] = "denied"
    try:  # charge without approval
        kit.charge_deposit(phone="x", amount=2000, idempotency_key="k", approval=None); res["charge w/o approval"] = "ran"
    except PermissionDenied:
        res["charge w/o approval"] = "denied"
    try:  # approval bound to amount
        kit.charge_deposit(phone="x", amount=5000, idempotency_key="k2",
                           approval={"approval_id": "AP-1", "status": "approved", "by": "manager", "amount": 2000})
        res["charge different amount"] = "ran"
    except PermissionDenied:
        res["charge different amount"] = "denied"
    try:  # > 8 booking without deposit receipt
        kit.create_booking("A", "p", "2026-11-07", "19:00", 12, "k3"); res["group booking w/o deposit"] = "ran"
    except PermissionDenied:
        res["group booking w/o deposit"] = "denied"
    shutil.rmtree(d)
    return {"pass": all(v == "denied" for v in res.values()), **res}


def test_default_desk_fails_closed():
    d, kit, desk, agent, clock = _setup(script={})        # nobody scripted -> nobody answers
    t0 = clock.now()
    r = agent.run(RINA, resume=False)
    out = {"pass": r["status"] == "pending_manager" and not kit.deposits and r["approval"]["status"] == "timeout",
           "waited s": clock.now() - t0, "deposits": len(kit.deposits)}
    shutil.rmtree(d); return out


def test_step_cap_stops_before_acting():
    old = ba.STEP_CAP
    ba.STEP_CAP = 3
    try:
        d, kit, desk, agent, _ = _setup({"B04": "approve"})
        r = agent.run(RINA, resume=False)
        out = {"pass": r["status"] == "handed_to_staff" and not kit.deposits and r["step"] <= 3,
               "steps": r["step"], "deposits": len(kit.deposits),
               "last message": kit.messages[-1]["body"]}
    finally:
        ba.STEP_CAP = old
    shutil.rmtree(d); return out


def test_context_has_no_other_guests_or_cards():
    d, kit, desk, agent, _ = _setup()
    inj = next(c for c in CHATS if c["chat_id"] == "B11")
    mem = SeatingMemory(d / "mem.json"); mem.set(inj["phone"], "booth")
    sp = Scratchpad.open(inj, d / "runs", resume=False)
    clean, flags = ba.sanitize(inj["turns"][0])
    ctx = build_context(sp, clean, mem)
    blob = str(ctx)
    others = [b["phone"] for b in kit.bookings.values()] + [b["guest_name"] for b in kit.bookings.values()]
    out = {"pass": "4111" not in blob and not any(o in blob for o in others) and "<guest_message>" in blob,
           "flags": flags, "seating_preference": ctx["seating_preference"]}
    shutil.rmtree(d); return out


ALL = [
    ("resume: deposit_charged written -> never charge again", test_resume_after_deposit_saved),
    ("resume: crash between charge and write -> idempotency key", test_resume_after_charge_before_write),
    ("resume: booking_id set -> only confirm", test_resume_booking_id_set_only_confirms),
    ("retry recovers from 2 transient errors (1s + 2s)", test_retry_recovers),
    ("money is never blindly retried", test_no_retry_on_money),
    ("breaker opens after 5 fails -> staff call-back", test_breaker_opens_and_falls_back),
    ("permission scope + approval binding", test_permission_scope),
    ("unanswered manager -> 10 min lane, no charge", test_default_desk_fails_closed),
    ("step cap stops before acting", test_step_cap_stops_before_acting),
    ("context: no other guests, no card numbers", test_context_has_no_other_guests_or_cards),
]

if __name__ == "__main__":
    for name, fn in ALL:
        r = fn(); print(("PASS " if r["pass"] else "FAIL ") + name, r)
