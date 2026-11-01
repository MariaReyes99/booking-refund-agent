"""Web user interface for the two agents in this project.

    Customer Support Agent  (support_agent.py + supportkit_mock.py)   -> /  "Support desk" tab
    Bistro Uno Booking Agent (booking_agent.py)                        -> /  "Bistro Uno" tab

Run from the project folder (the one that holds support_agent.py and booking_agent.py):

    uv add flask            # once  (or: pip install flask)
    uv run python web_app.py
    open http://127.0.0.1:8000

Or start it from either notebook:  import web_app; web_app.launch_in_background()

Nothing here changes how the agents decide. The UI only plays the human roles:
  * Support desk: every approval the agent asks for (reply, refund, escalation review) is
    shown in the browser. You approve, reject, or let it time out. Unanswered = fails closed.
  * Bistro Uno: you chat as the guest, and act as the manager for groups of more than 8.
All backends are the local mocks. No real customer, order or payment system is touched.
"""
from __future__ import annotations

import builtins
import io
import json
import shutil
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
RUNS = ROOT / "runs"
MEM = ROOT / "memory"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

app = Flask(__name__, static_folder=None)

# ------------------------------------------------------------------ optional password (set it before deploying)
# Locally there is no password. On a server set DUTY_DESK_PASSWORD; the browser then asks for a login
# (any username + that password). Without it, anyone who can reach the URL can press Approve.
import hmac  # noqa: E402
import os  # noqa: E402
from flask import Response  # noqa: E402

DESK_PASSWORD = os.environ.get("DUTY_DESK_PASSWORD") or None


@app.before_request
def _require_password():
    if not DESK_PASSWORD or request.path == "/healthz":
        return None
    auth = request.authorization
    if not auth or not hmac.compare_digest((auth.password or "").encode(), DESK_PASSWORD.encode()):
        return Response("Login required: any username, plus the DUTY_DESK_PASSWORD.", 401,
                        {"WWW-Authenticate": 'Basic realm="Agent Duty Desk", charset="UTF-8"'})
    return None


@app.get("/healthz")
def healthz():  # unauthenticated liveness check for hosting platforms
    return {"ok": True}

# ------------------------------------------------------------------ load the agents
if not (ROOT / "booking_agent.py").exists() or not (WEB / "index.html").exists():
    raise SystemExit(f"[web_app] booking_agent.py and web/index.html must sit next to web_app.py in {ROOT}. "
                     "Unzip Agent_Duty_Desk.zip into this folder, keeping the web/ subfolder.")
import booking_agent as ba  # noqa: E402  (always present: shipped with this UI)

try:
    import support_agent as sa
    from support_agent import HumanDesk, SupportAgent
    from supportkit_mock import TICKETS, SupportKit
    SUPPORT_OK, SUPPORT_ERR = True, None
except Exception as e:  # the UI still serves the booking agent if the support modules are missing
    sa = None
    SUPPORT_OK, SUPPORT_ERR = False, f"{type(e).__name__}: {e}"

try:
    import run_tests as rt
except Exception:
    rt = None
try:
    import booking_tests as bt
except Exception:
    bt = None


# ------------------------------------------------------------------ input()/print() bridge
# HumanDesk(interactive=True) asks its questions with input() and may print context with print().
# Inside an agent worker thread both are routed to the browser; everywhere else they behave normally.
_tls = threading.local()
_orig_input = builtins.input


def _web_input(prompt=""):
    session = getattr(_tls, "session", None)
    if session is None:
        return _orig_input(prompt)
    return session.ask_human(str(prompt))


builtins.input = _web_input


class _ThreadAwareStdout(io.TextIOBase):
    def __init__(self, orig):
        self.orig = orig

    def write(self, s):
        session = getattr(_tls, "session", None)
        if session is not None and s.strip():
            session.log(s.rstrip("\n"))
        return self.orig.write(s)

    def flush(self):
        return self.orig.flush()


if not isinstance(sys.stdout, _ThreadAwareStdout):
    sys.stdout = _ThreadAwareStdout(sys.stdout)


def _json_safe(obj):
    return json.loads(json.dumps(obj, default=str))


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


# ================================================================== SUPPORT DESK
class SupportSession:
    """One support run at a time (input() is process-wide). The kit persists until reset."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.kit = SupportKit() if SUPPORT_OK else None
        self.run_dir = RUNS / "web_support"
        self.mem_path = MEM / "web_support.json"
        shutil.rmtree(self.run_dir, ignore_errors=True)
        self.mem_path.unlink(missing_ok=True)
        self.running = False
        self.ticket_id = None
        self.pending = None          # {"id", "prompt", "asked_at", "lane_s"}
        self._answer = None
        self._event = threading.Event()
        self.logs = []
        self.history = []            # finished runs, newest first
        self.error = None

    def log(self, line):
        self.logs.append({"t": time.time(), "line": line})

    # called from the agent thread through input()
    def ask_human(self, prompt):
        lane = getattr(sa, "TIME_LANE_S", 900)
        self.pending = {"id": uuid.uuid4().hex[:8], "prompt": prompt, "asked_at": time.time(), "lane_s": lane}
        self.log(f"HUMAN DESK ▸ {prompt.strip()}")
        self._event.clear()
        answered = self._event.wait(timeout=lane)
        ans = self._answer if answered else ""
        self.log(f"HUMAN DESK ◂ {ans or '(no answer: time lane expired)'}")
        self.pending, self._answer = None, None
        return ans

    def answer(self, pending_id, decision):
        if not self.pending or self.pending["id"] != pending_id:
            return False
        self._answer = {"approve": "approve", "reject": "reject", "timeout": ""}.get(decision, decision)
        self._event.set()
        return True

    def start(self, ticket, mode, script, use_openai, resume):
        if self.running:
            raise RuntimeError("A ticket is already running. Answer or time out the pending approval first.")
        self.running, self.ticket_id, self.logs, self.error = True, ticket.get("ticket_id"), [], None
        threading.Thread(target=self._run, args=(ticket, mode, script, use_openai, resume), daemon=True).start()

    def _run(self, ticket, mode, script, use_openai, resume):
        _tls.session = self
        tid = ticket.get("ticket_id", "T??")
        n_replies = len(self.kit.replies)
        n_esc = len(self.kit.escalations)
        refunds_before = set(self.kit.refunds)
        started = time.time()
        try:
            if not resume:
                (self.run_dir / f"{tid}.json").unlink(missing_ok=True)
            gen = None
            if use_openai:
                from openai_reply import OpenAIReplyGenerator
                gen = OpenAIReplyGenerator.from_env()
            desk = HumanDesk(interactive=True) if mode == "live" else HumanDesk(script={tid: script})
            agent = SupportAgent(self.kit, desk, run_dir=self.run_dir, memory_path=self.mem_path,
                                 classifier=gen.classify if gen else None, reply_generator=gen)
            out = agent.run(ticket)
            res = {
                "ticket_id": tid, "subject": ticket.get("subject"), "mode": mode, "ok": True,
                "seconds": round(time.time() - started, 1),
                "out": _json_safe(out),
                "replies": _json_safe([r for r in self.kit.replies[n_replies:]]),
                "escalations": _json_safe(self.kit.escalations[n_esc:]),
                "refunds": _json_safe([v for k, v in self.kit.refunds.items() if k not in refunds_before]),
                "account_changes": _json_safe(getattr(self.kit, "account_changes", [])),
                "scratchpad": _read_json(self.run_dir / f"{tid}.json"),
            }
        except Exception as e:
            res = {"ticket_id": tid, "ok": False, "error": f"{type(e).__name__}: {e}",
                   "trace": traceback.format_exc(limit=6)}
            self.error = res["error"]
        finally:
            _tls.session = None
            self.running = False
        res["log"] = list(self.logs)
        self.history.insert(0, res)

    def state(self):
        return {"running": self.running, "ticket_id": self.ticket_id, "pending": self.pending,
                "log": self.logs[-200:], "latest": self.history[0] if self.history else None,
                "history": [{"ticket_id": h["ticket_id"], "ok": h["ok"],
                             "status": (h.get("out") or {}).get("status"), "mode": h.get("mode")}
                            for h in self.history[:20]],
                "store": self.store()}

    def store(self):
        if not self.kit:
            return None
        return _json_safe({"replies": len(self.kit.replies), "escalations": len(self.kit.escalations),
                           "refunds": list(self.kit.refunds.values()),
                           "account_changes": getattr(self.kit, "account_changes", [])})


SUPPORT = SupportSession()


def _ticket_preview(t):
    text = next((t[k] for k in ("body", "message", "text", "content", "description") if isinstance(t.get(k), str)), "")
    sender = next((t[k] for k in ("from", "sender", "email", "customer_email", "from_email") if isinstance(t.get(k), str)), "")
    return {"ticket_id": t.get("ticket_id"), "subject": t.get("subject", ""), "preview": text, "sender": sender,
            "expect": t.get("expect", {})}


@app.get("/api/support/tickets")
def support_tickets():
    if not SUPPORT_OK:
        return jsonify({"ok": False, "error": SUPPORT_ERR})
    return jsonify({"ok": True, "tickets": [_ticket_preview(t) for t in TICKETS],
                    "raw": _json_safe({t["ticket_id"]: {k: v for k, v in t.items() if k != "expect"} for t in TICKETS}),
                    "openai_available": _openai_available()})


def _openai_available():
    try:
        import openai_reply  # noqa: F401
        return True
    except Exception:
        return False


@app.post("/api/support/run")
def support_run():
    if not SUPPORT_OK:
        return jsonify({"ok": False, "error": SUPPORT_ERR}), 400
    body = request.get_json(force=True)
    ticket = body.get("ticket")
    if isinstance(ticket, str):
        try:
            ticket = json.loads(ticket)
        except json.JSONDecodeError as e:
            return jsonify({"ok": False, "error": f"Ticket JSON is not valid: {e}"}), 400
    if not isinstance(ticket, dict) or "ticket_id" not in ticket:
        return jsonify({"ok": False, "error": "Ticket must be a JSON object with a ticket_id."}), 400
    original = next((t for t in TICKETS if t["ticket_id"] == ticket["ticket_id"]), None)
    if original and "expect" in original and "expect" not in ticket:
        ticket["expect"] = original["expect"]
    script = {k: v for k, v in (body.get("script") or {}).items() if v}
    try:
        SUPPORT.start(ticket, body.get("mode", "live"), script, bool(body.get("use_openai")), bool(body.get("resume")))
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True})


@app.get("/api/support/state")
def support_state():
    if not SUPPORT_OK:
        return jsonify({"ok": False, "error": SUPPORT_ERR})
    return jsonify({"ok": True, **SUPPORT.state()})


@app.post("/api/support/answer")
def support_answer():
    body = request.get_json(force=True)
    ok = SUPPORT.answer(body.get("id"), body.get("decision", ""))
    return jsonify({"ok": ok})


@app.post("/api/support/reset")
def support_reset():
    if SUPPORT.running:
        return jsonify({"ok": False, "error": "Wait for the running ticket to finish."}), 409
    SUPPORT.reset()
    return jsonify({"ok": True})


# ================================================================== BISTRO UNO BOOKINGS
class RealClock:
    now = staticmethod(time.time)
    sleep = staticmethod(time.sleep)


class WebManagerDesk(ba.ManagerDesk):
    """The manager answers in the browser. 10-minute time lane; silence = timeout = nothing charged."""

    def __init__(self, hub):
        super().__init__(clock=RealClock())
        self.hub = hub

    def request(self, chat_id, kind, summary, amount):
        rec = {"approval_id": f"AP-{uuid.uuid4().hex[:6]}", "chat_id": chat_id, "kind": kind, "by": "manager",
               "amount": amount, "summary": summary, "requested_at": time.time(),
               "lane_s": self.hub.lane_s, "status": "pending"}
        ev = threading.Event()
        self.hub.pending[rec["approval_id"]] = (rec, ev)
        answered = ev.wait(timeout=self.hub.lane_s)
        decision = rec.get("decision") if answered else None
        rec["status"] = {"approve": "approved", "reject": "rejected"}.get(decision, "timeout")
        rec["waited_s"] = round(time.time() - rec["requested_at"], 1)
        self.hub.pending.pop(rec["approval_id"], None)
        self.hub.decided.insert(0, dict(rec))
        self.log.append(rec)
        return {k: v for k, v in rec.items() if k not in ("decision", "lane_s")}


class BookingHub:
    OPEN_STATES = {"open", "awaiting_guest", "offered_alternatives", "offered_smaller"}

    def __init__(self):
        self.lock = threading.Lock()
        self.lane_s = ba.MANAGER_TIME_LANE_S
        self.reset()

    def reset(self):
        self.run_dir = RUNS / "web_booking"
        self.mem_path = MEM / "web_booking.json"
        shutil.rmtree(self.run_dir, ignore_errors=True)
        self.mem_path.unlink(missing_ok=True)
        self.kit = ba.BistroKit()
        self.pending = {}            # approval_id -> (rec, Event)
        self.decided = []
        self.desk = WebManagerDesk(self)
        self.agent = ba.BookingAgent(self.kit, self.desk, self.run_dir, self.mem_path, clock=RealClock())
        self.chats = {}              # chat_id -> {"chat", "transcript", "seen", "running"}
        self._n = 0

    def _new_chat(self, guest_name, phone):
        self._n += 1
        cid = f"W{self._n:03d}"
        self.chats[cid] = {"chat": {"chat_id": cid, "guest_name": guest_name, "phone": phone, "turns": []},
                           "transcript": [], "seen": 0, "running": False, "error": None}
        return cid

    def post(self, chat_id, guest_name, phone, text):
        with self.lock:
            c = self.chats.get(chat_id)
            if c and c["running"]:
                raise RuntimeError("The assistant is still working on your last message.")
            status = (self.scratchpad(chat_id) or {}).get("status") if c else None
            if (not c or (status and status not in self.OPEN_STATES)
                    or c["chat"]["phone"] != phone or c["chat"]["guest_name"] != guest_name):
                chat_id = self._new_chat(guest_name, phone)     # finished chat or new guest -> new conversation
                c = self.chats[chat_id]
            c["chat"]["turns"].append(text)
            c["transcript"].append({"from": "guest", "text": text, "t": time.time()})
            c["running"], c["error"] = True, None
        threading.Thread(target=self._run, args=(chat_id,), daemon=True).start()
        return chat_id

    def _run(self, chat_id):
        c = self.chats[chat_id]
        try:
            self.agent.run(c["chat"], resume=True)
        except Exception as e:
            c["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            mine = [m for m in self.kit.messages if m["chat_id"] == chat_id]
            for m in mine[c["seen"]:]:
                c["transcript"].append({"from": "agent", "text": m["body"], "t": time.time()})
            c["seen"] = len(mine)
            c["running"] = False

    def scratchpad(self, chat_id):
        return _read_json(self.run_dir / f"{chat_id}.json")

    def decide(self, approval_id, decision):
        item = self.pending.get(approval_id)
        if not item:
            return False
        rec, ev = item
        rec["decision"] = decision
        ev.set()
        return True

    def state(self, chat_id):
        c = self.chats.get(chat_id)
        now = time.time()
        pend = [{**{k: v for k, v in rec.items() if k != "decision"},
                 "remaining_s": max(0, int(rec["requested_at"] + self.lane_s - now))}
                for rec, _ in self.pending.values()]
        return _json_safe({
            "chat_id": chat_id if c else None,
            "transcript": c["transcript"] if c else [],
            "running": c["running"] if c else False,
            "error": c["error"] if c else None,
            "scratchpad": self.scratchpad(chat_id) if c else None,
            "pending": pend,
            "decided": self.decided[:10],
            "bookings": sorted(self.kit.bookings.values(), key=lambda b: b["booking_id"], reverse=True),
            "deposits": list(self.kit.deposits.values()),
            "manager_notes": self.kit.manager_notes[-10:][::-1],
            "memory": _read_json(self.mem_path) or {},
            "lane_s": self.lane_s,
            "limits": {"step_cap": ba.STEP_CAP, "question_cap": ba.QUESTION_CAP},
        })


BOOKING = BookingHub()


@app.post("/api/booking/message")
def booking_message():
    b = request.get_json(force=True)
    text = (b.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Type a message first."}), 400
    name = (b.get("guest_name") or "Guest").strip()[:40]
    phone = (b.get("phone") or "").strip()[:30] or "+63 900 000 0000"
    try:
        cid = BOOKING.post(b.get("chat_id"), name, phone, text[:1000])
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True, "chat_id": cid})


@app.get("/api/booking/state")
def booking_state():
    return jsonify({"ok": True, **BOOKING.state(request.args.get("chat_id"))})


@app.post("/api/booking/decide")
def booking_decide():
    b = request.get_json(force=True)
    return jsonify({"ok": BOOKING.decide(b.get("approval_id"), b.get("decision"))})


@app.post("/api/booking/settings")
def booking_settings():
    b = request.get_json(force=True)
    if "lane_s" in b:
        BOOKING.lane_s = max(10, min(int(b["lane_s"]), ba.MANAGER_TIME_LANE_S))
    return jsonify({"ok": True, "lane_s": BOOKING.lane_s})


@app.post("/api/booking/reset")
def booking_reset():
    if any(c["running"] for c in BOOKING.chats.values()):
        return jsonify({"ok": False, "error": "Wait for the running chat to finish."}), 409
    BOOKING.reset()
    return jsonify({"ok": True})


@app.get("/api/booking/samples")
def booking_samples():
    return jsonify({"ok": True, "samples": [{"chat_id": c["chat_id"], "subject": c["subject"], "text": c["turns"][0],
                                             "guest_name": c["guest_name"], "phone": c["phone"]} for c in ba.CHATS]})


# ================================================================== TEST SUITES + DESIGN
@app.post("/api/tests/support")
def tests_support():
    if not (SUPPORT_OK and rt):
        return jsonify({"ok": False, "error": SUPPORT_ERR or "run_tests.py not found"})
    out = {"ok": True}
    try:
        rows, inv = rt.run_ticket_suite()
        out["tickets"] = _json_safe(rows)
        out["invariants"] = _json_safe(inv)
    except Exception as e:
        out["tickets_error"] = f"{type(e).__name__}: {e}"
    names = [("resume after crash — no double refund", "test_resume_no_double_refund"),
             ("retry recovers from 2 transient errors", "test_retry_recovers"),
             ("breaker opens -> human fallback", "test_breaker_opens_and_falls_back"),
             ("permission scope + approval binding", "test_permission_scope"),
             ("human can block any reply", "test_reply_rejected_by_human"),
             ("default approver fails closed", "test_default_human_desk_fails_closed"),
             ("model draft requires approval", "test_openai_draft_is_human_approved"),
             ("model failure never sends", "test_model_failure_never_sends_reply"),
             ("model cannot downgrade rules", "test_model_cannot_downgrade_rule_classification"),
             ("OpenAI SDK injected-client test", "test_openai_reply_generator_uses_sdk_without_network"),
             ("scratchpad retries transient file locks", "test_scratchpad_retries_transient_replace_lock")]
    out["controls"] = []
    for label, fn in names:
        f = getattr(rt, fn, None)
        if not f:
            continue
        try:
            r = f()
            out["controls"].append({"name": label, "pass": bool(r.get("pass")),
                                    "evidence": _json_safe({k: v for k, v in r.items() if k != "pass"})})
        except Exception as e:
            out["controls"].append({"name": label, "pass": False, "evidence": f"{type(e).__name__}: {e}"})
    return jsonify(out)


@app.post("/api/tests/booking")
def tests_booking():
    rows, inv, kit, desk = ba.run_chat_suite(str(RUNS / "booking_suite"), str(MEM / "booking_suite.json"))
    out = {"ok": True, "chats": _json_safe(rows), "invariants": inv, "controls": []}
    if bt:
        for name, fn in bt.ALL:
            r = fn()
            out["controls"].append({"name": name, "pass": bool(r["pass"]),
                                    "evidence": _json_safe({k: v for k, v in r.items() if k != "pass"})})
    return jsonify(out)


@app.get("/api/design")
def design():
    d = {"booking": {"tools": ba.tool_rating_table(),
                     "settings": {k: getattr(ba, k) for k in ["GROUP_LIMIT", "DEPOSIT_PHP", "ALTERNATIVES", "RETRY_BACKOFF_S",
                                                               "BREAKER_THRESHOLD", "BREAKER_COOLDOWN_S", "MANAGER_TIME_LANE_S",
                                                               "STEP_CAP", "QUESTION_CAP"]}}}
    if SUPPORT_OK:
        keys = ["REFUND_LIMIT_NZD", "REFUND_WINDOW_DAYS", "AUTO_CLOSE_MIN_CONFIDENCE", "UNKNOWN_BELOW_CONFIDENCE", "SAFE_LIST",
                "RETRY_BACKOFF_S", "BREAKER_THRESHOLD", "BREAKER_COOLDOWN_S", "TIME_LANE_S", "STEP_CAP", "QUESTION_CAP", "LLM_CALL_CAP"]
        d["support"] = {"tools": _json_safe(sa.tool_rating_table()) if hasattr(sa, "tool_rating_table") else [],
                        "settings": _json_safe({k: sorted(v) if isinstance(v, set) else v
                                                for k in keys if hasattr(sa, k) for v in [getattr(sa, k)]})}
    else:
        d["support_error"] = SUPPORT_ERR
    diagrams = sorted(p.name for p in (ROOT / "diagrams").glob("*.png")) if (ROOT / "diagrams").exists() else []
    d["diagrams"] = diagrams
    return jsonify(d)


@app.get("/diagrams/<path:name>")
def diagram(name):
    return send_from_directory(ROOT / "diagrams", name)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "support": SUPPORT_OK, "support_error": SUPPORT_ERR, "booking": True,
                    "run_tests": rt is not None, "booking_tests": bt is not None})


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/web/<path:name>")
def web_static(name):
    return send_from_directory(WEB, name)


# ------------------------------------------------------------------ launch helpers
_server_thread = None
_server_url = None


def _check_files():
    missing = [str(p.relative_to(ROOT)) for p in (WEB / "index.html", ROOT / "booking_agent.py") if not p.exists()]
    if missing:
        raise SystemExit(f"[web_app] Missing {', '.join(missing)} next to web_app.py in {ROOT}. "
                         "Unzip Agent_Duty_Desk.zip into this folder, keeping the web/ subfolder.")


def _make_server(host, port, tries=20):
    """Bind to `port`, or the next free one if it is taken (a common cause of 'refused to connect')."""
    import socket
    from werkzeug.serving import make_server
    last = None
    for p in range(port, port + tries):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((host, p))          # free? (werkzeug would sys.exit on a busy port, so test first)
        except OSError as e:               # address already in use / permission denied
            last = e
            print(f"[web_app] Port {p} is not available ({e.strerror or e}). Trying {p + 1}...")
            continue
        finally:
            probe.close()
        try:
            return make_server(host, p, app, threaded=True), p
        except (OSError, SystemExit) as e:
            last = e
            print(f"[web_app] Port {p} could not be used. Trying {p + 1}...")
    raise SystemExit(f"[web_app] No free port between {port} and {port + tries - 1}: {last}")


def launch_in_background(port=8000, host="127.0.0.1", open_browser=False):
    """Start the UI from a notebook cell without blocking it. Returns the URL.
    The server lives as long as the notebook kernel: restart the kernel and you must run this cell again."""
    global _server_thread, _server_url
    if _server_thread is None or not _server_thread.is_alive():
        _check_files()
        srv, used = _make_server(host, port)
        _server_thread = threading.Thread(target=srv.serve_forever, daemon=True)
        _server_thread.start()
        _server_url = f"http://{host}:{used}"
    print(f"Agent web UI running at {_server_url}  (keep this kernel running)")
    if open_browser:
        import webbrowser
        webbrowser.open(_server_url)
    return _server_url


if __name__ == "__main__":
    import argparse
    import webbrowser
    p = argparse.ArgumentParser(description="Web UI for the support and booking agents")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    a = p.parse_args()
    _check_files()
    if not SUPPORT_OK:
        print(f"[web_app] Support agent not loaded ({SUPPORT_ERR}). The Bistro Uno tab still works.")
    srv, used = _make_server(a.host, a.port)
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '::') else a.host}:{used}"
    print(f"[web_app] Agent Duty Desk is running at {url}")
    print("[web_app] Leave this window open while you use it. Press Ctrl+C to stop.")
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[web_app] Stopped.")
