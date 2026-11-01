@echo off
REM Double-click to start the Agent Duty Desk. Leave this window open while you use it.
cd /d "%~dp0"
where uv >nul 2>nul
if %errorlevel%==0 (
  uv add flask >nul 2>nul
  uv run python web_app.py
) else (
  python -m pip install --quiet flask
  python web_app.py
)
echo.
echo The web app has stopped. Read any error above, then press a key to close.
pause >nul
