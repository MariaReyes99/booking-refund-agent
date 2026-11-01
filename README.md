# Customer Support Agent

## What this project does today

The notebook and `support_agent.py` run against `supportkit_mock.py`, a local
simulation of customers, orders, tickets, approvals, and refunds. The real
course `supportkit` and a production help-desk/order backend are not installed
or configured here. **Do not point the mock at real customer or payment data.**

The existing Python workflow provides deterministic routing, tool execution,
and policy checks. You can optionally add OpenAI classification and reply
drafting; deterministic high-risk rules take precedence, and model output is
reviewed by the existing evaluator and must receive human approval before it
is sent. The model cannot issue refunds or change accounts. The default agent
remains offline and uses deterministic classification and draft text.

## Environment

From the project directory:

```powershell
uv sync
uv run python run_tests.py
```

In VS Code, select the project `.venv` interpreter. For the notebook, select
the **customer-support-agent** Python 3.13 kernel. Repeat `uv sync` after
changing `pyproject.toml` or `uv.lock`, or after pulling dependency changes.

## Optional OpenAI reasoning

The Python integration reads `OPENAI_API_KEY` and `CHAT_MODEL` from the process
environment or `.env.local`. No key is printed or included in model prompts.
OpenAI use is **off unless both** of these settings are explicitly enabled:

```dotenv
SUPPORT_AGENT_OPENAI_ENABLED=true
SUPPORT_AGENT_TICKET_DATA_CONSENT=true
```

Enabling this sends the ticket ID, subject, card-number-masked message, first
name, issue class, and verified facts to the configured OpenAI API. Only enable
it if your privacy, customer notice, and data-processing requirements permit
that transfer. The `.env.local` file is ignored by Git; never paste keys into
source code, notebooks, or chat.

Use the model-backed classifier and draft generator explicitly:

```python
from openai_reply import OpenAIReplyGenerator
from support_agent import HumanDesk, SupportAgent
from supportkit_mock import SupportKit

reply_generator = OpenAIReplyGenerator.from_env()
agent = SupportAgent(
    SupportKit(),
    HumanDesk(interactive=True),
    classifier=reply_generator.classify,
    reply_generator=reply_generator,
)
```

`HumanDesk(interactive=True)` asks a person to approve each reply and refund.
Without an interactive approver or an explicit scripted test decision, the
agent fails closed and does not send the reply or issue the refund. Scripted
approvals are for tests only, not production authorization.

## Before connecting a live support system

There is no production backend adapter in this project. A real deployment
needs a provider-specific, authenticated integration for ticket intake,
verified sender identity, customer/order lookup, durable escalation, and
approval tracking. Keep write operations disabled until the provider enforces
authenticated human approvals and idempotent refund handling. The mock
`SupportKit` simulates these behaviors; its approvals and refund records are
not production controls.

The test suite uses the mock backend and injected model clients only; it does
not call OpenAI or any live support/payment service.
