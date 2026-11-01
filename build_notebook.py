import nbformat as nbf
nb = nbf.v4.new_notebook()
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
c = []
c.append(md("""# Customer Support Agent — Agent Design Sheet implementation
**Week 17A patterns + Week 17B controls.** Hybrid pattern: **Router** (`classify_ticket`) → **ReAct** tool loop → **Evaluator** (Reflexion-style critic).

**Human in the loop on every ticket.** Nothing reaches a customer and no money moves until a person approves:
| Action | Who approves | If nobody answers in 15 min |
|---|---|---|
| Every outbound reply | Support agent (Legal/Security for escalations) | Not sent; ticket waits in human queue |
| Refund ≤ NZ\\$100 | Support agent | No refund, holding reply |
| Refund > NZ\\$100 | Manager | No refund, holding reply |
| Legal threat / prompt injection | Counter-model **and** Legal / Security person | Stays escalated |
| Account change / closure | Accounts team (tools not exposed to the agent) | — |

> `supportkit_mock.py` is a local simulation; no live support or order backend is installed. OpenAI classification and draft generation are optional and disabled by default. They send ticket text to OpenAI only when both `SUPPORT_AGENT_OPENAI_ENABLED=true` and `SUPPORT_AGENT_TICKET_DATA_CONSENT=true` are set in `.env.local`."""))
c.append(code("""import json, shutil
from pathlib import Path
from IPython.display import Image, display, Markdown
import support_agent as sa
from support_agent import SupportAgent, HumanDesk, tool_rating_table, build_context, Scratchpad
from supportkit_mock import SupportKit, TICKETS
USE_OPENAI_AGENT = False
reply_generator = None
if USE_OPENAI_AGENT:
    from openai_reply import OpenAIReplyGenerator
    reply_generator = OpenAIReplyGenerator.from_env()
print("Allowlist:", sorted(sa.ALLOWLIST))"""))
c.append(md("## Part 4 · Tools rated before they are exposed"))
c.append(code("""rows = tool_rating_table()
display(Markdown("| Tool | Effect | Reversible? | Autonomy | Breaker group |\\n|---|---|---|---|---|\\n" +
    "\\n".join(f"| `{r['tool']}` | {r['effect']} | {r['reversible']} | {r['autonomy']} | {r['breaker group']} |" for r in rows)))"""))
c.append(md("## Part 3 · Controls — exact settings"))
c.append(code("""for k in ["REFUND_LIMIT_NZD","REFUND_WINDOW_DAYS","AUTO_CLOSE_MIN_CONFIDENCE","UNKNOWN_BELOW_CONFIDENCE","SAFE_LIST",
          "RETRY_BACKOFF_S","BREAKER_THRESHOLD","BREAKER_COOLDOWN_S","TIME_LANE_S","STEP_CAP","QUESTION_CAP","LLM_CALL_CAP"]:
    print(f"{k:28} = {getattr(sa, k)}")"""))
c.append(md("## Part 2 · What one model call sees (ticket T08 — the prompt-injection ticket)\nThe card number is stripped, the message is wrapped as untrusted data, and the customer record is masked."))
c.append(code("""tmp = Path("runs/demo"); shutil.rmtree(tmp, ignore_errors=True)
kit = SupportKit(); t08 = TICKETS[7]
sp = Scratchpad.open("T08", tmp, resume=False); sp["issue_class"] = "security"
ctx = build_context(sp, t08, kit.customers["C-400"], sa.EpisodicMemory(tmp / "mem.json"))
print(json.dumps(ctx, indent=2))"""))
c.append(md("## Run all 12 tickets\nApprovals are explicitly scripted for this mock test: the manager **times out** on T06 and **rejects** T07. Unscripted approvals fail closed."))
c.append(code("""run_dir = Path("runs/notebook"); shutil.rmtree(run_dir, ignore_errors=True)
mem = Path("memory/notebook.json"); mem.unlink(missing_ok=True)
kit = SupportKit()
script = {t["ticket_id"]: {"reply": "approve"} for t in TICKETS}
for ticket in TICKETS:
    expected = ticket["expect"]
    if "approver" in expected:
        script[ticket["ticket_id"]]["refund"] = expected.get("human_script", "approve")
    if expected.get("queue") in ("security", "legal"):
        script[ticket["ticket_id"]]["escalation_review"] = "approve"
script["T06"]["refund"] = "timeout"
script["T07"]["refund"] = "reject"
desk = HumanDesk(script=script)
agent = SupportAgent(kit, desk, run_dir=run_dir, memory_path=mem,
                     classifier=reply_generator.classify if reply_generator else None,
                     reply_generator=reply_generator)
results = [agent.run(t) for t in TICKETS]
table = "| Ticket | Class | Conf | Branch | Status | Refund | Human gates |\\n|---|---|---|---|---|---|---|\\n"
for t, r in zip(TICKETS, results):
    gates = "<br>".join(f"{a['role']}: {a['kind']} **{a['status']}**" for a in r["approvals"])
    table += f"| {t['ticket_id']} {t['subject']} | {r['issue_class']} | {r['confidence']} | {r['decisions'][0]['branch']} | {r['status']} | {r['refund_id'] or '-'} | {gates} |\\n"
display(Markdown(table))"""))
c.append(code("""print("Replies sent (every one human-approved):\\n")
for r in kit.replies:
    print(f"{r['ticket_id']}: {r['body']}\\n")
print("Escalations:", [(e['ticket_id'], e['queue']) for e in kit.escalations])
print("Refunds paid:", [(v['refund_id'], v['order_id'], v['amount']) for v in kit.refunds.values()])
print("Account changes made by agent:", kit.account_changes)"""))
c.append(md("### The scratchpad for T05 (NZ$340 refund, manager approved)\nSame base format as the course scratchpad (`run_id`, `started_at`, `last_step_index`, `observations`, `decisions`), extended with ticket state."))
c.append(code("""print((run_dir / "T05.json").read_text())"""))
c.append(md("## Control tests\nResume after a crash (no double refund), tool retry/circuit breaker, approval safety, OpenAI guards, and transient scratchpad file-lock retry."))
c.append(code("""import run_tests as rt
rows, inv = rt.run_ticket_suite()
print(f"{sum(r['pass'] for r in rows)}/12 tickets pass")
print(json.dumps(inv, indent=1))
for name, fn in [("resume after crash — no double refund", rt.test_resume_no_double_refund),
                 ("retry recovers from 2 transient errors", rt.test_retry_recovers),
                 ("breaker opens -> human fallback", rt.test_breaker_opens_and_falls_back),
                 ("permission scope + approval binding", rt.test_permission_scope),
                 ("human can block any reply", rt.test_reply_rejected_by_human),
                 ("default approver fails closed", rt.test_default_human_desk_fails_closed),
                 ("model draft requires approval", rt.test_openai_draft_is_human_approved),
                 ("model failure never sends", rt.test_model_failure_never_sends_reply),
                 ("model cannot downgrade rules", rt.test_model_cannot_downgrade_rule_classification),
                 ("OpenAI SDK injected-client test", rt.test_openai_reply_generator_uses_sdk_without_network),
                 ("scratchpad retries transient file locks", rt.test_scratchpad_retries_transient_replace_lock)]:
    res = fn(); print(("PASS " if res["pass"] else "FAIL ") + name); print("   ", res)"""))
c.append(md("## Try it yourself — human approval\nSet `INTERACTIVE = True` to approve or reject each action. To use OpenAI classification and drafts, set `USE_OPENAI_AGENT = True` in the setup cell and explicitly enable both OpenAI consent settings in `.env.local`; this sends ticket text to OpenAI."))
c.append(code("""INTERACTIVE = False
if INTERACTIVE:
    d = Path("runs/interactive"); shutil.rmtree(d, ignore_errors=True)
    live = SupportAgent(SupportKit(), HumanDesk(interactive=True), run_dir=d,
                        memory_path=Path("memory/interactive.json"),
                        classifier=reply_generator.classify if reply_generator else None,
                        reply_generator=reply_generator)
    out = live.run(TICKETS[4])   # T05: NZ$340 refund -> you act as the manager
    print(out["status"], out["refund_id"])"""))
c.append(md("## Diagrams"))
for f, t in [("1_sequence", "Part 1 · Sequence diagram with controls tagged where they fire"),
             ("2_branches", "Branches, including unknown"), ("3_hitl_states", "Human-approval lifecycle"),
             ("4_architecture", "Hybrid architecture"), ("5_memory", "Part 2 · Memory and context")]:
    c.append(md(f"### {t}")); c.append(code(f'display(Image("diagrams/{f}.png", width=900))'))
nb["cells"] = c
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "Customer_Support_Agent.ipynb")
