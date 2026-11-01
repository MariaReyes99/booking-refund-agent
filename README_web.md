# Agent Duty Desk: web UI for the support and booking agents

## Install (project folder = the one with `support_agent.py`)

Copy these into your project folder, keeping the layout:

```
web_app.py
web/index.html
booking_agent.py          (updated: live multi-turn chats)
booking_tests.py
diagrams/6_booking_sequence.png ... 9_booking_memory.png
Customer_Support_Agent.ipynb              (adds a "Web user interface" launch cell at the end)
Customer_Support_and_Booking_Agent.ipynb  (same, plus Part B)
```

Then, once:

```
uv add flask        # or: pip install flask
```

## Run

**Windows:** double-click `start_web.bat` (or run `uv run python web_app.py` as ONE command in PowerShell). Your browser opens automatically. Keep the black window open: closing it stops the app.

**Mac/Linux:** `./start_web.sh`

If port 8000 is busy, the app moves to 8001, 8002, ... and prints the address it used.


```
uv run python web_app.py          # then open http://127.0.0.1:8000
uv run python web_app.py --port 8050
```

Or run the last cell of either notebook (`web_app.launch_in_background()`).

## What each tab does

| Tab | What you do | What it uses |
|---|---|---|
| Support desk | Pick a ticket, optionally edit its text, run it. In **I approve live** mode each human gate (reply, refund, escalation review) appears as a decision slip: Approve, Reject, or leave it unanswered (fails closed after the time lane). **Decide in advance** uses `HumanDesk(script=...)` like the notebook. | `SupportAgent`, `HumanDesk`, `TICKETS`, `SupportKit` |
| Bistro Uno bookings | Chat as the guest (name + phone). Groups of more than 8 send you a manager slip. The 10-minute time lane can be shortened to 60 s or 20 s for demos. Staff view shows bookings, deposits, the manager queue, remembered seating preferences and the scratchpad. | `booking_agent.BookingAgent`, `BistroKit` |
| Test suites | Runs `run_tests.py` (12 tickets + control tests) and `booking_agent.run_chat_suite()` + `booking_tests.py`. | same functions as the notebooks |
| Design sheet | Tool ratings, exact settings and every PNG in `diagrams/`. | `tool_rating_table()`, module constants |

## How live approvals work

`HumanDesk(interactive=True)` asks its questions with `input()`. While a ticket runs, the web app routes that `input()` (and anything the agent prints) from the worker thread to the browser, and returns your button press as the typed answer: `approve`, `reject`, or blank (time out). Nothing in the agent changes. If your `HumanDesk` expects different answer words (for example `y`/`n`), change the mapping in `SupportSession.answer()` in `web_app.py`.

## Safety notes

- Runs locally only (`127.0.0.1`). It is a teaching demo, not a production approval system: there is no login, so anyone who can reach the port can approve.
- All backends are mocks. OpenAI drafts appear as an option only if `openai_reply.py` is present, and still need both consent settings in `.env.local`.
- If `support_agent.py` cannot be imported, the Support desk tab shows why and the Bistro Uno tab keeps working.
