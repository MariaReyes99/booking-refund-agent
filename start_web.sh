#!/usr/bin/env bash
# Start the Agent Duty Desk (Mac/Linux). Leave this terminal open while you use it.
cd "$(dirname "$0")"
if command -v uv >/dev/null; then uv add flask >/dev/null 2>&1; uv run python web_app.py; else python3 -m pip install --quiet flask; python3 web_app.py; fi
