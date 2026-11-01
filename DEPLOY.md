# Deploying the Agent Duty Desk

The app must run as ONE long-lived process (approvals and chats are held in memory),
so use a host that runs a normal web server: Render, Railway, Fly.io, Azure App Service.
Not Vercel or other serverless hosts.

## 1. Prepare the folder (once)

In PowerShell, in `Agent_Assignment`:

```
uv add gunicorn
uv export --no-hashes --format requirements-txt > requirements.txt
Rename-Item gitignore.txt .gitignore
```

Check `.gitignore` is there before pushing: it keeps `.env.local` (your API key) out of GitHub.

## 2. Push to a PRIVATE GitHub repository

```
git init
git add .
git commit -m "Agent Duty Desk"
git branch -M main
git remote add origin https://github.com/<you>/agent-duty-desk.git
git push -u origin main
```

## 3. Deploy on Render

1. render.com > New > Blueprint > pick the repo. `render.yaml` sets the build and start commands.
2. When asked, type a `DUTY_DESK_PASSWORD`.
3. Open the `https://agent-duty-desk-xxxx.onrender.com` link. Log in with any username + that password.

(Without the blueprint: New > Web Service, build `pip install -r requirements.txt`,
start command from `Procfile`, and add `DUTY_DESK_PASSWORD` under Environment.)

## Good to know

- Free instances sleep when idle; the first visit can take about a minute.
- `runs/` and `memory/` reset on every restart or redeploy. Fine for mock data.
- OpenAI drafts: add `OPENAI_API_KEY`, `SUPPORT_AGENT_OPENAI_ENABLED=true` and
  `SUPPORT_AGENT_TICKET_DATA_CONSENT=true` as Render environment variables. Never commit `.env.local`.
- Keep `--workers 1`. More workers split the in-memory approvals across processes and Approve clicks get lost.
