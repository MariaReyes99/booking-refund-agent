const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, ImageRun, AlignmentType, LevelFormat, PageBreak, BorderStyle, Footer, PageNumber,
} = require("docx");

const R = JSON.parse(fs.readFileSync("test_results.json", "utf8"));
const SIZES = JSON.parse(fs.readFileSync("diagrams/sizes.json", "utf8"));
const W = 9026; // A4 content width in DXA (1" margins)
const PURPLE = "6B2F74", LIGHT = "F3EEF6", GREEN = "E6F4EA", AMBER = "FFF4E0", RED = "FDE8E8";

const p = (text, opts = {}) => new Paragraph({ spacing: { after: 120 }, ...opts,
  children: Array.isArray(text) ? text : [new TextRun(text)] });
const b = (t) => new TextRun({ text: t, bold: true });
const t = (s) => new TextRun(s);
const code = (s) => new TextRun({ text: s, font: "Consolas", size: 19 });
const h1 = (s) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(s)] });
const h2 = (s) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(s)] });
const bullet = (runs) => new Paragraph({ numbering: { reference: "bul", level: 0 }, spacing: { after: 60 },
  children: typeof runs === "string" ? [new TextRun(runs)] : runs });
const brk = () => new Paragraph({ children: [new PageBreak()] });

function cell(content, width, fill, bold = false) {
  const runs = (Array.isArray(content) ? content : String(content ?? "").split("\n")).map(
    (line) => new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: line, bold, size: 18,
      color: bold && fill === PURPLE ? "FFFFFF" : undefined })] }));
  return new TableCell({ width: { size: width, type: WidthType.DXA }, children: runs,
    shading: fill ? { fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 90, right: 90 } });
}
function table(headers, rows, widths, rowFill) {
  const total = widths.reduce((a, c) => a + c, 0);
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], PURPLE, true)) }),
      ...rows.map((r, ri) => new TableRow({ children: r.map((c, i) =>
        cell(c, widths[i], rowFill ? rowFill(r, ri) : (ri % 2 ? LIGHT : undefined))) }))] });
}
function img(name, maxW = 600, maxH = 820) {
  const [w, h] = SIZES[name];
  let sw = maxW, sh = Math.round(h * maxW / w);
  if (sh > maxH) { sh = maxH; sw = Math.round(w * maxH / h); }
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [
    new ImageRun({ type: "png", data: fs.readFileSync(`diagrams/${name}.png`), transformation: { width: sw, height: sh } })] });
}
const caption = (s) => p([new TextRun({ text: s, italics: true, size: 18, color: "555555" })], { alignment: AlignmentType.CENTER });

// ---------------------------------------------------------------- content
const children = [];
children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Customer Support Agent")] }));
children.push(p([new TextRun({ text: "Agent Design Sheet · v3 · OpenAI-ready, mock-backend only", color: PURPLE, size: 26 })]));
children.push(p("A controlled hybrid customer-support agent for a fictional NZ online store. Deterministic policy and tool controls remain authoritative; an optional, explicitly consented OpenAI path classifies ordinary tickets and drafts replies. Every outbound message and refund still requires an explicit human approval."));
children.push(table(["", "Summary"], [
  ["What is implemented", "Deterministic mock ticket/order/knowledge-base tools; optional OpenAI classification and reply drafts; evaluator; scratchpad and retry controls."],
  ["Where a person steps in", "Every outbound reply and refund. Refunds ≤ NZ$100 require support approval; larger refunds require manager approval. Legal/security cases are escalated for review. Missing approval fails closed."],
  ["What is not production-ready", "The real course supportkit and production help-desk, identity, order, and payment adapters are not installed. All backend tools and approvals in the demo are simulated."],
  ["What it never does", "Agent-made account changes; refunds without matching approval; action on silence; prompt-directed tool use; disclosure of another customer's data."],
], [2200, 6826]));

// ---------------------------------------------------------------- review
children.push(brk(), h1("0 · Review of the v1 design against the brief"));
children.push(p("The v1 document (Copilot-elaborated) gets the main ideas right: a NZ$100 refund gate, two-factor judgment for legal tickets, close_account not exposed, a scratchpad written after every step, a last-3-steps context rule, and step and question caps. It falls short of the brief in four places: the sequence diagram has no control tags, there is no resume rule, the tools are not rated by effect and reversibility, and nothing was tested against the 12 tickets. v2 fixes each gap below."));
children.push(table(["Brief requirement", "v1 status", "Gap", "Fixed in v2"], [
  ["1 · Sequence diagram: every actor, loop, condition, control tagged", "Partial",
   "No control tags. Router calls tools directly. No clarify loop, unknown branch, timeout path, or order-ownership check. Help desk, evaluator and legal team missing as actors.",
   "Full sequence diagram with 12 control tags at the step where each fires (§1)."],
  ["2 · Memory: schema, what each call sees, persists, never, resume rule", "Partial",
   "Field list only — no when-written / who-reads / when-deleted. No cross-chat memory spec. No resume rule (the brief asks how to avoid refunding twice after a crash).",
   "Field-lifecycle table, context rule, episodic + procedural memory, and a tested resume rule using an idempotency key (§2)."],
  ["3 · Controls: where, exact setting, reason + what was left out", "Partial",
   "Only 3 controls have where/why. Retry is '1-2-4 s' in text but '1 s, 2 s' in the figure. 'Refund > $100' leaves exactly $100 undefined. 15-min time lane has no safe default. No 'left out' section.",
   "11 controls, each with where / setting / why; boundary defined as ≤ NZ$100; time-lane safe default; deliberately-left-out list (§3)."],
  ["4 · Tools: every tool rated by effect + reversibility, autonomy or 'not exposed'", "Partial",
   "Autonomy only. Two refund tools (under/over 100) let the model choose the risky one. escalate_case marked HITL though it is a hand-off to people. send_reply 'auto' conflicts with always-HITL. Only close_account listed as not exposed.",
   "One issue_refund with the limit enforced in code; 12 tools rated; 4 not exposed (§4)."],
  ["Refunds above and below a limit", "Covered", "Approval not bound to the amount — an approval for $45 could be reused for $340.", "Approval bound to order + amount hash and approver role; tested."],
  ["Prompt injection", "Weak", "'Security escalation' only — no detection point, no rule that ticket text is data, no check on tool outputs.", "Guard at intake and on every tool output; amounts only from records; tested on T08."],
  ["Account changes the agent must not make", "Partial", "close_account only.", "change_account_email, update_payment_method, close_account, refund_override all not exposed; tested on T09."],
  ["Legal threats that must escalate", "Covered", "Counter-model not specified.", "Counter-model = independent risk score + legal reviewer; tested on T10."],
  ["Branch conditions (Step 2)", "Missing", "Branches named but conditions not written; no unknown fallback condition.", "Exact conditions for all four branches (§1)."],
  ["Test against all 12 tickets", "Missing", "—", "12/12 pass + 11 control tests (§7)."],
], [2000, 900, 3426, 2700], (r, i) => r[1] === "Missing" ? RED : r[1] === "Weak" ? AMBER : r[1] === "Covered" ? GREEN : (i % 2 ? LIGHT : undefined)));

// ---------------------------------------------------------------- part 1
children.push(brk(), h1("1 · Sequence diagram"));
children.push(p("Every actor, every alt/opt condition, and each control tagged where it fires. Tags in square brackets: [GUARD], [SCOPE], [RETRY], [BREAKER], [BRANCH], [HITL GATE], [TIME LANE], [SAFE DEFAULT], [TWO-FACTOR], [STOPS]."));
children.push(img("1_sequence", 560, 800));
children.push(caption("Figure 1 — One ticket, end to end, with controls tagged where they fire"));
children.push(brk(), h2("Branches, including unknown"));
children.push(img("2_branches", 600, 420));
children.push(caption("Figure 2 — classify_ticket() and the condition on every branch"));
children.push(table(["Branch", "Exact condition", "What happens", "Human"], [
  ["auto_close", "class ∈ {order_status, how_to} AND confidence ≥ 0.85", "Read-only lookups, safe template reply", "Support agent approves the reply (one click)"],
  ["route_to_human", "class = refund or account_change, or 0.50 ≤ confidence < 0.85", "Refund: agent proposes, person approves. Account change: hand-off to accounts.", "Support agent (≤ NZ$100) / manager (> NZ$100) / accounts team"],
  ["escalate", "class = legal_threat, or injection flags found", "Counter-model risk score + escalation case; neutral acknowledgement", "Legal or security reviewer (two-factor)"],
  ["unknown", "confidence < 0.50 or no class matched", "One clarifying question (max 3) + general human queue", "Support agent approves the question"],
], [1400, 2700, 2726, 2200]));

// ---------------------------------------------------------------- part 2
children.push(brk(), h1("2 · Memory and context"));
children.push(img("5_memory", 600, 470));
children.push(caption("Figure 3 — What is written, what each call reads, what never enters"));
children.push(h2("Working scratchpad — runs/<ticket_id>.json, written after every step"));
children.push(p("Keeps the course scratchpad's base format (run_id, started_at, last_step_index, observations, decisions) and adds ticket state. Writes are atomic (write temp file, then replace), so a crash never leaves a half-written file."));
children.push(table(["Field(s)", "Written when", "Read by", "Deleted when"], [
  ["run_id, started_at, last_step_index, observations[], decisions[]", "Open; every step", "Context (last 3 steps), auditors", "Kept with ticket 90 days"],
  ["customer_id", "After lookup_customer on the verified sender email", "All tools", "90 days"],
  ["issue_class, confidence, branch, injection_flags[]", "Intake + classify; flags also on every tool output", "Router, evaluator, security reviewer", "90 days"],
  ["evidence{}, proposed_action", "After lookups, before any approval", "Drafting, human approver", "90 days"],
  ["refund_amount, approver_role_required, idempotency_key", "BEFORE the approval request and before any money call", "Human desk, issue_refund, resume rule", "Kept with refund record (financial retention)"],
  ["approvals[] (role, status, payload hash, wait time)", "On every human decision", "Approval check in tool registry, resume rule, audit", "Financial retention"],
  ["refund_id, escalation_case_id", "After the tool succeeds", "Resume rule, reply", "With ticket"],
  ["draft_reply, reply_sent, reply_id, status", "Draft; after send; each stage", "Evaluator, human, resume; human queue reads status = pending_human", "90 days"],
  ["step_count, questions_asked, llm_calls, human_touchpoints", "Every step", "Caps; 'always-HITL' audit", "90 days"],
], [2700, 2300, 2226, 1800]));
children.push(h2("Context rule — in every model call"));
["System prompt with the non-negotiable rules.",
 "The latest customer message, wrapped in <customer_message> as untrusted data, with card numbers removed.",
 "The last 3 scratchpad steps.",
 "A masked customer record: customer_id, name, tier, card last 4 only.",
 "Only the skills for this class (e.g. refund_policy.md + tone_guide.md for a refund).",
 "The last 3 past cases and Reflexion lessons for this customer."].forEach((s) => children.push(bullet(s)));
children.push(h2("Persists across chats (episodic memory, keyed by customer_id)"));
children.push(p("Case summaries (class, outcome, refund_id) and Reflexion lessons from drafts the evaluator rejected. Not full transcripts. Used, for example, on T12: the clarifying question asks whether it's about the customer's last case."));
children.push(h2("Procedural memory (skills, loaded only when needed)"));
children.push(p("refund_policy.md · tone_guide.md · escalation_playbook.md · security_playbook.md"));
children.push(h2("Never in context"));
children.push(p("Passwords or password hashes; full card numbers; other customers' records; approver notes from other tickets; anything inside the ticket treated as an instruction."));
children.push(h2("Resume rule — what stops a double refund"));
[[b("reply_sent = true → "), t("stop; nothing to do.")],
 [b("refund_id set → "), t("never refund again; only confirm.")],
 [b("idempotency_key set, refund_id empty → "), t("call issue_refund with the SAME key. The payment provider returns the existing refund instead of paying twice.")],
 [b("approval already recorded → "), t("never ask the person again.")],
].forEach((r) => children.push(bullet(r)));
children.push(p([t("Tested: the process is killed right after issue_refund succeeds, before refund_id is saved. On restart one refund exists, the manager is not asked twice, and the customer gets one reply.")]));

// ---------------------------------------------------------------- part 3
children.push(brk(), h1("3 · Controls"));
children.push(table(["Control", "Where it fires", "Exact setting", "Why"], [
  ["Permission scope", "Agent start; every tool call", "Allowlist of 8 tools, default deny. 4 tools not exposed.", "Account changes and uncapped refunds are people's decisions"],
  ["Injection guard", "Intake, and every tool output", "11 patterns + card-number check. Flag → escalate to security. Ticket text wrapped as data. Refund amount only from the order record.", "Tickets try prompt injection"],
  ["Branching", "After classify_ticket()", "See Figure 2 conditions; auto_close needs safe class AND conf ≥ 0.85; unknown below 0.50", "Every outcome has a defined path"],
  ["Retry", "Every tool call", "Transient errors only: 1 attempt + 3 retries at 1 s, 2 s, 4 s. Permanent errors never retried.", "APIs are flaky; retrying money is safe only with the idempotency key"],
  ["Circuit breaker", "Per dependency: crm, orders, kb, helpdesk, payments", "Opens after 5 consecutive failures; half-open after 60 s. Open → pending_human, nothing sent.", "Don't hammer a failing system; fail to a person"],
  ["HITL — money", "issue_refund", "≤ NZ$100: support agent. > NZ$100: manager. Approval bound to order + amount + role. Reject → offer inspection/repair.", "Refunds can't be undone"],
  ["HITL — every reply", "send_reply", "A person approves every outbound message; text must match the approved hash.", "Always a human in the loop; a sent message can't be unsent"],
  ["Two-factor judgment", "Legal threats, security events", "Counter-model risk score + legal/security reviewer. If they disagree, take the cautious path.", "Compliance and legal exposure"],
  ["Time lane", "Any approval", "15 min. Then: no money moves, escalate_case(refunds), holding reply.", "Never act on silence"],
  ["Stops", "Whole ticket", "12 steps, 3 questions, 6 model calls. Hit → pending_human; a person writes the reply.", "No loops, no interrogation, bounded cost"],
  ["Evaluator (Reflexion)", "Before a person sees a draft", "Checks: no false refund claim, no other customer's data, no card number, no echoed injection, no admission of liability, not empty. Fail → holding reply + lesson saved.", "Catch errors before they reach the approver"],
], [1600, 1900, 3326, 2200]));
children.push(h2("Deliberately left out"));
[[b("Auto-sending auto_close replies. "), t("Faster, but the brief for this build is 'always a human in the loop'. Once accuracy is proven, this could drop to sampled review (e.g. 10%).")],
 [b("Counter-model on refunds. "), t("The money action already has a human gate bound to the amount; a second model adds latency without reducing risk.")],
 [b("Agent-made account changes, even with approval. "), t("Identity verification is a human process; the tools stay unexposed.")],
 [b("Full transcripts in episodic memory. "), t("Privacy; outcome summaries are enough for continuity.")],
].forEach((r) => children.push(bullet(r)));
children.push(img("3_hitl_states", 380, 500));
children.push(caption("Figure 4 — Lifecycle of every human approval"));

// ---------------------------------------------------------------- part 4
children.push(brk(), h1("4 · Tools"));
children.push(p("Rule of thumb from the example: reads run alone, internal writes run alone, anything a customer sees or money touches waits for a person, and account tools are never exposed."));
const toolNotes = {
  lookup_customer: "By verified sender email only", lookup_order: "Ownership checked against customer_id",
  list_orders: "Sender's own orders only", search_kb: "Output scanned for injection",
  update_ticket: "Internal status", escalate_case: "Hand-off to people — safe to run alone",
  send_reply: "Every reply, approved text hash", issue_refund: "≤ $100 support agent, > $100 manager",
  change_account_email: "Accounts team after ID check", update_payment_method: "Accounts team",
  close_account: "Accounts team", refund_override: "Back-office manager only",
};
const toolRows = Object.entries(toolNotes).map(([n, note]) => {
  const spec = { lookup_customer: ["read", "yes", "auto"], lookup_order: ["read", "yes", "auto"], list_orders: ["read", "yes", "auto"],
    search_kb: ["read", "yes", "auto"], update_ticket: ["write (internal)", "yes", "auto"], escalate_case: ["write (hand-off)", "yes", "auto"],
    send_reply: ["write (customer-facing)", "no", "after human approval"], issue_refund: ["money", "no", "after human approval + idempotency key"],
    change_account_email: ["account", "partly", "not exposed"], update_payment_method: ["account", "partly", "not exposed"],
    close_account: ["account", "no", "not exposed"], refund_override: ["money (no limit)", "no", "not exposed"] }[n];
  return [n, ...spec, note];
});
children.push(table(["Tool", "Effect", "Reversible?", "Autonomy", "Note"], toolRows, [2350, 1500, 1050, 2126, 2000],
  (r, i) => r[3] === "not exposed" ? RED : r[3].startsWith("after") ? AMBER : (i % 2 ? LIGHT : undefined)));

// ---------------------------------------------------------------- architecture
children.push(brk(), h1("5 · Hybrid architecture"));
children.push(img("4_architecture", 600, 420));
children.push(caption("Figure 5 — Router + ReAct + Evaluator, with the controls layer between the agent and the tools"));
children.push(p("The controls are enforced in code (the tool registry), not only in the prompt. Even if a ticket fooled the model into calling issue_refund or close_account, the registry would refuse: close_account isn't on the allowlist, and issue_refund needs an approved human decision whose role, order and amount match."));

// ---------------------------------------------------------------- AI and deployment boundary
children.push(brk(), h1("6 · Optional AI reasoning and deployment boundary"));
children.push(p("When enabled, the OpenAI integration classifies routine tickets and drafts customer replies. It receives the ticket ID, subject, card-number-masked message, customer first name, issue class, verified facts, and a deterministic safe-draft seed. The seed constrains the model to rephrase verified content; it must not add facts or promises. Full sender email, card number, and customer database records are not sent."));
children.push(table(["Control", "Design"], [
  ["Default", "Offline. OpenAI classification and drafting are disabled unless both SUPPORT_AGENT_OPENAI_ENABLED=true and SUPPORT_AGENT_TICKET_DATA_CONSENT=true."],
  ["High-risk precedence", "Injection flags route deterministically to security. The model cannot downgrade a higher-risk deterministic classification."],
  ["AI authority", "Model output is a proposal, never a tool call or approval. The existing allowlist, evaluator, human gates, refund policy, and idempotency key remain authoritative."],
  ["Model failure", "Invalid output or API failure fails closed to the human queue. No model failure silently falls back to sending an unreviewed message."],
  ["Human approval", "Interactive approvals require an explicit approve/reject response. Unconfigured or missing approvers time out; they do not approve by default."],
  ["Endpoint and privacy", "Enable only after reviewing customer notice, privacy, and data-processing requirements for the configured API endpoint. Keys remain in .env.local and are never placed in prompts."],
  ["Production status", "No live support/order/payment adapter or authenticated approval service is installed. Mock approvals, refunds, and queues are not production controls."],
], [1900, 7126]));
children.push(p([b("Next implementation step. "), t("Choose a real help-desk and order provider, implement a provider-specific adapter with verified identity, durable audit/approval records, and idempotent writes, then test in a staging environment before enabling any production write.")]));

// ---------------------------------------------------------------- tests
children.push(brk(), h1("7 · Test results — 12 tickets"));
children.push(p([t("Run with "), code("uv run python run_tests.py"), t(" or the notebook. These tests use only the local simulation in supportkit_mock.py and an injected fake model client; they do not call OpenAI or a live support/payment service.")]));
const nPass = R.tickets.filter((x) => x.pass).length;
children.push(p([b(`${nPass}/12 tickets pass. `), t(`Total simulated refunds: NZ$${R.invariants.total_refunded_nzd.toFixed(2)}. Every ticket had at least one explicit human decision; every reply sent was human-approved; no unexposed tool was called; no account changes were made.`)]));
children.push(table(["#", "Ticket", "Class", "Branch", "Outcome", "Human decisions"],
  R.tickets.map((x) => [x.ticket, x.subject, `${x.class} (${x.confidence})`, x.branch,
    x.final_status + (x.refund_id ? `\nrefund ${x.refund_id} NZ$${x.refund_amount}` : "") + (x.escalated_to ? `\n→ ${x.escalated_to}` : ""),
    x.human_gates.map((g) => g.replace(/_/g, " ").replace(":", ": ").replace("=", " → ")).join("\n")]),
  [550, 1500, 1450, 1550, 1650, 2326], (r, i) => (i % 2 ? LIGHT : undefined)));
children.push(h2("Control tests"));
const ctl = R.controls;
const controls = [
  ["Crash after refund, then resume", "resume_after_crash_no_double_refund",
    (x) => `refund calls ${x.issue_refund_calls}; distinct refunds ${x.distinct_refunds_paid}; approver asked twice: ${x.manager_asked_again}`],
  ["Retry recovers from transient errors", "retry_recovers_from_2_transient_errors",
    (x) => `order lookup attempts ${x.lookup_order_attempts}; status ${x.final_status}`],
  ["Circuit breaker fails to human queue", "circuit_breaker_opens_then_human_fallback",
    (x) => `breaker ${x.breaker_state} after ${x.lookup_order_attempts_total} lookup attempts; no reply sent`],
  ["Permission scope and approval binding", "permission_scope_and_approval_binding",
    () => "Dangerous tools, missing approvals, insufficient roles, and mismatched amounts are blocked."],
  ["Human can block any reply", "human_can_block_any_reply",
    (x) => `status ${x.status}; replies sent ${x.replies_sent}`],
  ["Missing approver fails closed", "default_human_desk_fails_closed",
    (x) => `status ${x.status}; approval ${x.approval_status}; replies sent ${x.replies_sent}`],
  ["AI draft requires human approval", "model_draft_requires_human_approval",
    (x) => `model calls ${x.model_calls}; approval ${x.approval_status}; reply sent ${x.reply_sent}`],
  ["Model failure never sends", "model_failure_never_sends_reply",
    (x) => `status ${x.status}; reply sent ${x.reply_sent}`],
  ["Model cannot downgrade deterministic class", "model_classification_cannot_downgrade_rules",
    (x) => `selected class ${x.selected_class}; refund issued ${x.refund_issued}`],
  ["OpenAI integration with injected client", "openai_sdk_integration_uses_injected_client",
    (x) => `classification ${x.classification.issue_class}; fake client only`],
  ["Scratchpad retries transient file locks", "scratchpad_retries_transient_file_locks",
    (x) => `atomic replace attempts ${x.replace_attempts}; ticket persisted ${x.saved_ticket_id}`],
];
children.push(table(["Test", "Result", "Evidence"], controls.map(([label, key, evidence]) => {
  const result = ctl[key];
  return [label, result && result.pass ? "PASS" : "FAIL",
    result ? evidence(result) : "No recorded result"];
}), [3000, 900, 5126], (r) => r[1] === "PASS" ? GREEN : RED));

// ---------------------------------------------------------------- build
const doc = new Document({
  creator: "Customer Support Agent design", title: "Customer Support Agent — Agent Design Sheet v3",
  styles: {
    default: { document: { run: { font: "Calibri", size: 21 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { size: 48, bold: true, color: PURPLE }, paragraph: { spacing: { after: 80 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, color: PURPLE }, paragraph: { spacing: { before: 120, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, color: "3B1F47" }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1300, bottom: 1300, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
      new TextRun({ text: "Customer Support Agent · Design Sheet v3 · page ", size: 16, color: "888888" }),
      new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "888888" })] })] }) },
    children,
  }],
});
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync("Customer_Support_Agent_Design_v3.docx", buf); console.log("written"); });
