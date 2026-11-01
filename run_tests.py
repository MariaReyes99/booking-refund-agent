"""
run_tests.py — runs the agent against all 12 tickets, then tests each control.
Writes test_results.json and prints a summary table.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from support_agent import (ALLOWLIST, HumanDesk, PermissionDenied, Scratchpad, SupportAgent,
                           STEP_CAP, QUESTION_CAP, ReplyGenerationError, SimulatedCrash, TOOL_SPECS)
from openai_reply import OpenAIReplyGenerator
from supportkit_mock import TICKETS, SupportKit

BASE = Path(__file__).resolve().parent
NOT_EXPOSED = {n for n, s in TOOL_SPECS.items() if s.autonomy == "not_exposed"}


def fresh_dirs(name):
    d = BASE / "runs" / name
    shutil.rmtree(d, ignore_errors=True)
    m = BASE / "memory" / f"{name}.json"
    m.unlink(missing_ok=True)
    return d, m


def human_script():
    """Explicit scripted decisions for the mock test suite."""
    script = {t["ticket_id"]: {"reply": "approve"} for t in TICKETS}
    for ticket in TICKETS:
        expected = ticket["expect"]
        if "approver" in expected:
            script[ticket["ticket_id"]]["refund"] = expected.get("human_script", "approve")
        if "queue" in expected and expected["queue"] in ("security", "legal"):
            script[ticket["ticket_id"]]["escalation_review"] = "approve"
    return script


def run_ticket_suite():
    run_dir, mem = fresh_dirs("tickets")
    kit = SupportKit()
    desk = HumanDesk(script=human_script())
    agent = SupportAgent(kit, desk, run_dir=run_dir, memory_path=mem)
    rows, checks = [], []
    for t in TICKETS:
        sp = agent.run(t)
        exp = t["expect"]
        refunded = sp["refund_id"] is not None
        branches = [d["branch"] for d in sp["decisions"]]
        approvals = [f"{a['role']}:{a['kind']}={a['status']}" for a in sp["approvals"]]
        reply = next((r["body"] for r in kit.replies if r["ticket_id"] == t["ticket_id"]), None)
        esc = next((e for e in kit.escalations if e["ticket_id"] == t["ticket_id"]), None)
        ok = {
            "branch": branches[0] == exp["branch"],
            "refund": refunded == exp["refund"],
            "human_in_loop": sp["human_touchpoints"] >= 1,
            "caps": sp["step_count"] <= STEP_CAP and sp["questions_asked"] <= QUESTION_CAP,
        }
        if "approver" in exp:
            ok["approver"] = any(a["kind"] == "refund" and a["role"] == exp["approver"] for a in sp["approvals"])
        if "queue" in exp:
            ok["queue"] = esc is not None and esc["queue"] == exp["queue"]
        if reply:
            ok["no_leak"] = "5555" not in reply and "ben@" not in reply and "Ben Carter" not in reply \
                            if t["sender_email"] != "ben@example.co.nz" else "5555" not in reply
        rows.append({"ticket": t["ticket_id"], "subject": t["subject"], "class": sp["issue_class"],
                     "confidence": sp["confidence"], "branch": branches[0],
                     "final_status": sp["status"], "refund_id": sp["refund_id"],
                     "refund_amount": sp["refund_amount"], "human_gates": approvals,
                     "escalated_to": esc["queue"] if esc else None, "steps": sp["step_count"],
                     "reply": reply, "pass": all(ok.values()), "checks": ok})
        checks.append(all(ok.values()))
    # global invariants
    called = {c[0] for c in kit.calls}
    invariants = {
        "no_unexposed_tool_ever_called": not (called & NOT_EXPOSED),
        "no_account_changes_made": kit.account_changes == [],
        "every_refund_has_matching_approval": all(
            any(a["kind"] == "refund" and a["status"] == "approved" for a in
                json.loads((run_dir / f"{r['ticket']}.json").read_text())["approvals"])
            for r in rows if r["refund_id"]),
        "every_reply_was_human_approved": len(kit.replies) == sum(
            1 for r in rows for g in r["human_gates"] if ":reply=approved" in g),
        "every_ticket_had_a_human": all(len(r["human_gates"]) >= 1 for r in rows),
        "total_refunded_nzd": sum(r["amount"] for r in kit.refunds.values()),
    }
    return rows, invariants


def test_resume_no_double_refund():
    run_dir, mem = fresh_dirs("resume")
    kit = SupportKit()
    t = next(x for x in TICKETS if x["ticket_id"] == "T05")
    approvals = HumanDesk(script={"T05": {"refund": "approve", "reply": "approve"}})
    agent = SupportAgent(kit, approvals, run_dir=run_dir, memory_path=mem, crash_after="issue_refund")
    crashed = False
    try:
        agent.run(t)
    except SimulatedCrash:
        crashed = True
    sp_mid = json.loads((run_dir / "T05.json").read_text())
    # restart: new process, same scratchpad + same payment provider
    agent2 = SupportAgent(kit, approvals, run_dir=run_dir, memory_path=mem)
    sp = agent2.run(t)
    refund_calls = [c for c in kit.calls if c[0] == "issue_refund"]
    return {"crashed_after_refund": crashed,
            "refund_id_in_scratchpad_at_crash": sp_mid["refund_id"],
            "idempotency_key_at_crash": sp_mid["idempotency_key"],
            "issue_refund_calls": len(refund_calls),
            "distinct_refunds_paid": len(kit.refunds),
            "manager_asked_again": sum(a["kind"] == "refund" for a in sp["approvals"]) > 1,
            "pass": crashed and len(kit.refunds) == 1 and sp["reply_sent"]
                    and sum(a["kind"] == "refund" for a in sp["approvals"]) == 1}


def test_retry_recovers():
    run_dir, mem = fresh_dirs("retry")
    kit = SupportKit(fail_plan={"lookup_order": 2})
    desk = HumanDesk(script={"T01": {"reply": "approve"}})
    sp = SupportAgent(kit, desk, run_dir=run_dir, memory_path=mem).run(TICKETS[0])
    tries = sum(1 for c in kit.calls if c[0] == "lookup_order")
    return {"lookup_order_attempts": tries, "final_status": sp["status"],
            "pass": tries == 3 and sp["reply_sent"]}


def test_breaker_opens_and_falls_back():
    run_dir, mem = fresh_dirs("breaker")
    kit = SupportKit(fail_plan={"lookup_order": "always"})
    agent = SupportAgent(kit, HumanDesk(), run_dir=run_dir, memory_path=mem)
    out = []
    for tid in ("T01", "T03"):
        sp = agent.run(next(t for t in TICKETS if t["ticket_id"] == tid))
        out.append({"ticket": tid, "status": sp["status"], "reply_sent": sp["reply_sent"],
                    "last_decision": sp["decisions"][-1]["reason"]})
    attempts = sum(1 for c in kit.calls if c[0] == "lookup_order")
    return {"runs": out, "lookup_order_attempts_total": attempts,
            "breaker_state": agent.tools.breakers["orders"].state,
            "pass": all(o["status"] == "pending_human" and not o["reply_sent"] for o in out)
                    and agent.tools.breakers["orders"].state == "open" and attempts == 5}


def test_permission_scope():
    run_dir, mem = fresh_dirs("perm")
    agent = SupportAgent(SupportKit(), HumanDesk(), run_dir=run_dir, memory_path=mem)
    from support_agent import Scratchpad
    sp = Scratchpad.open("PERM", run_dir, resume=False)
    results = {}
    for name, kw in [("close_account", {"customer_id": "C-100"}),
                     ("issue_refund", {"order_id": "SK-1003", "amount": 340.0, "idempotency_key": "x"})]:
        try:
            agent.tools.call(sp, name, **kw)
            results[name] = "EXECUTED (bad)"
        except PermissionDenied as e:
            results[name] = f"blocked: {e}"
    # a support-agent approval for NZ$340 must not be accepted
    fake = {"kind": "refund", "status": "approved", "role": "support_agent",
            "payload": {"order_id": "SK-1003", "amount": 340.0}}
    try:
        agent.tools.call(sp, "issue_refund", approval=fake, order_id="SK-1003", amount=340.0, idempotency_key="y")
        results["340_with_support_agent_approval"] = "EXECUTED (bad)"
    except PermissionDenied as e:
        results["340_with_support_agent_approval"] = f"blocked: {e}"
    # approval for one amount cannot be reused for another
    fake2 = dict(fake, role="manager", payload={"order_id": "SK-1006", "amount": 45.0})
    try:
        agent.tools.call(sp, "issue_refund", approval=fake2, order_id="SK-1006", amount=60.0, idempotency_key="z")
        results["approval_reused_for_other_amount"] = "EXECUTED (bad)"
    except PermissionDenied as e:
        results["approval_reused_for_other_amount"] = f"blocked: {e}"
    results["pass"] = all(v.startswith("blocked") for v in results.values())
    return results


def test_reply_rejected_by_human():
    run_dir, mem = fresh_dirs("reply_reject")
    kit = SupportKit()
    desk = HumanDesk(script={"T02": {"reply": "reject"}})
    sp = SupportAgent(kit, desk, run_dir=run_dir, memory_path=mem).run(TICKETS[1])
    return {"status": sp["status"], "replies_sent": len(kit.replies),
            "pass": sp["status"] == "pending_human" and len(kit.replies) == 0}


def test_default_human_desk_fails_closed():
    run_dir, mem = fresh_dirs("no_approver")
    kit = SupportKit()
    sp = SupportAgent(kit, HumanDesk(), run_dir=run_dir, memory_path=mem).run(TICKETS[0])
    return {"status": sp["status"], "replies_sent": len(kit.replies),
            "approval_status": sp["approvals"][-1]["status"],
            "pass": sp["status"] == "pending_human" and not kit.replies
                    and sp["approvals"][-1]["status"] == "timeout"}


def test_openai_draft_is_human_approved():
    class FakeReplyGenerator:
        def __init__(self):
            self.context = None

        def __call__(self, context):
            self.context = context
            return ("Kia ora Aroha, your order SK-1001 is shipped with NZ Post and is due by "
                    "2026-11-03. You can follow it with the tracking link in your dispatch email.")

    run_dir, mem = fresh_dirs("model_draft")
    kit = SupportKit()
    generator = FakeReplyGenerator()
    desk = HumanDesk(script={"T01": {"reply": "approve"}})
    sp = SupportAgent(kit, desk, run_dir=run_dir, memory_path=mem,
                      reply_generator=generator).run(TICKETS[0])
    return {"model_calls": sp["llm_calls"], "reply_sent": sp["reply_sent"],
            "approval_status": sp["approvals"][-1]["status"],
            "sender_email_in_model_context": "aroha@example.co.nz" in json.dumps(generator.context),
            "pass": sp["llm_calls"] == 1 and sp["reply_sent"]
                    and sp["approvals"][-1]["status"] == "approved"
                    and generator.context is not None
                    and "aroha@example.co.nz" not in json.dumps(generator.context)}


def test_model_failure_never_sends_reply():
    def fail(_context):
        raise ReplyGenerationError("test model outage")

    run_dir, mem = fresh_dirs("model_failure")
    kit = SupportKit()
    sp = SupportAgent(kit, HumanDesk(), run_dir=run_dir, memory_path=mem,
                      reply_generator=fail).run(TICKETS[0])
    return {"status": sp["status"], "reply_sent": sp["reply_sent"],
            "pass": sp["status"] == "pending_human" and not sp["reply_sent"]}


def test_model_cannot_downgrade_rule_classification():
    def misclassify(_context):
        return {"issue_class": "how_to", "confidence": 0.99}

    run_dir, mem = fresh_dirs("classification_guard")
    kit = SupportKit()
    desk = HumanDesk(script={"T03": {"refund": "approve", "reply": "approve"}})
    sp = SupportAgent(kit, desk, run_dir=run_dir, memory_path=mem,
                      classifier=misclassify).run(TICKETS[2])
    return {"selected_class": sp["issue_class"], "refund_issued": sp["refund_id"] is not None,
            "model_calls": sp["llm_calls"],
            "pass": sp["issue_class"] == "refund" and sp["refund_id"] is not None
                    and sp["llm_calls"] == 1}


def test_openai_reply_generator_uses_sdk_without_network():
    class FakeCompletions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            from types import SimpleNamespace
            content = ('{"issue_class":"order_status","confidence":0.9,"rationale":"tracking request"}'
                       if "response_format" in kwargs else "Thanks for contacting our team.")
            return SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content=content))
            ])

    from types import SimpleNamespace
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    generator = OpenAIReplyGenerator(model="test-model", client=client)
    reply = generator({"customer_message": "Where is my order?", "verified_facts": {}})
    sent = completions.kwargs["messages"][1]["content"]
    classification = generator.classify({"customer_message": "Where is my order?"})
    return {"reply_returned": reply, "model": completions.kwargs["model"],
            "context_sent": "Where is my order?" in sent,
            "classification": classification,
            "pass": reply == "Thanks for contacting our team."
                    and completions.kwargs["model"] == "test-model"
                    and "Where is my order?" in sent
                    and classification["issue_class"] == "order_status"}


def test_scratchpad_retries_transient_replace_lock():
    with tempfile.TemporaryDirectory(prefix="support-agent-save-test-") as temp_dir:
        attempts = 0
        real_replace = os.replace

        def fail_twice_then_replace(source, target):
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise PermissionError("simulated transient file lock")
            return real_replace(source, target)

        path = Path(temp_dir) / "runs"
        with mock.patch("support_agent.os.replace", side_effect=fail_twice_then_replace):
            with mock.patch("support_agent.time.sleep"):
                sp = Scratchpad.open("RETRY", path, resume=False)
        saved = json.loads((path / "RETRY.json").read_text())
    return {"replace_attempts": attempts,
            "saved_ticket_id": saved["ticket_id"],
            "pass": attempts == 3 and saved["ticket_id"] == "RETRY"}


if __name__ == "__main__":
    rows, inv = run_ticket_suite()
    controls = {
        "resume_after_crash_no_double_refund": test_resume_no_double_refund(),
        "retry_recovers_from_2_transient_errors": test_retry_recovers(),
        "circuit_breaker_opens_then_human_fallback": test_breaker_opens_and_falls_back(),
        "permission_scope_and_approval_binding": test_permission_scope(),
        "human_can_block_any_reply": test_reply_rejected_by_human(),
        "default_human_desk_fails_closed": test_default_human_desk_fails_closed(),
        "model_draft_requires_human_approval": test_openai_draft_is_human_approved(),
        "model_failure_never_sends_reply": test_model_failure_never_sends_reply(),
        "model_classification_cannot_downgrade_rules": test_model_cannot_downgrade_rule_classification(),
        "openai_sdk_integration_uses_injected_client": test_openai_reply_generator_uses_sdk_without_network(),
        "scratchpad_retries_transient_file_locks": test_scratchpad_retries_transient_replace_lock(),
    }
    print(f"{'T':4} {'class':15} {'conf':5} {'branch':15} {'status':18} {'refund':8} {'human gates'}")
    for r in rows:
        print(f"{r['ticket']:4} {r['class']:15} {r['confidence']!s:5} {r['branch']:15} {r['final_status']:18} "
              f"{(r['refund_id'] or '-'):8} {', '.join(r['human_gates'])}  {'PASS' if r['pass'] else 'FAIL ' + str(r['checks'])}")
    print("\nInvariants:", json.dumps(inv, indent=1))
    for k, v in controls.items():
        print(f"{'PASS' if v['pass'] else 'FAIL'}  {k}: {v}")
    out = {"tickets": rows, "invariants": inv, "controls": controls,
           "allowlist": sorted(ALLOWLIST), "not_exposed": sorted(NOT_EXPOSED)}
    (BASE / "test_results.json").write_text(json.dumps(out, indent=2, default=str))
    n_pass = sum(r["pass"] for r in rows)
    print(f"\n{n_pass}/12 tickets pass; {sum(v['pass'] for v in controls.values())}/{len(controls)} control tests pass")
