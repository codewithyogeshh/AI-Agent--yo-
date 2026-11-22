# NOVA — your personal autonomous AI operator

NOVA is a self-hosted agent that **plans, executes and verifies real work**: web research, file
production, video generation with ffmpeg, reminders and scheduling, plus approval-gated publishing
to YouTube/Instagram and email/calendar via official APIs. You control it from a responsive web
dashboard, an installable PWA, or WhatsApp.

This is a working application, not a mockup. Every tool either performs the action or reports
precisely what is missing (a credential, a public URL, an unsupported platform feature). Nothing is
faked: unfinished work shows as `setup_required`, never as success.

**Download:** [Source (ZIP)](https://github.com/codewithyogeshh/AI-Agent--yo-/archive/refs/heads/main.zip) · [Clone](https://github.com/codewithyogeshh/AI-Agent--yo-.git)

---

## Quick start (local)

```bash
# 1 — backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # then edit: set NOVA_SECRET_KEY
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

# 2 — frontend (new terminal)
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

Open <http://localhost:3000>, create the owner account (first-run only), and start assigning tasks.
The frontend proxies `/api/proxy/*` to the backend, so no CORS setup is needed in development.

**Only dependency you may not have:** `ffmpeg`. If it is missing, NOVA falls back to the static
binary shipped by `imageio-ffmpeg` (already installed with the requirements). On a server, install
ffmpeg properly (`apt install ffmpeg`).

---

## What works right now, without any API key

| Capability | Status |
|---|---|
| Task engine: plan → permission check → execute → verify → report | ✅ real |
| Durable queue, scheduler, retries, pause/cancel/emergency stop | ✅ real |
| Web research (DuckDuckGo search + page extraction + cited report) | ✅ real |
| Video production: script/scenes → mp4 (ffmpeg) → burned subtitles → thumbnail → metadata | ✅ real |
| Reminders and recurring tasks | ✅ real |
| Event triggers: signed webhooks → tasks, with payload templating, filters and retry dedupe | ✅ real (Gmail/calendar pollers next) |
| One-click YouTube/Instagram linking **and publishing** (managed OAuth — no developer app to create) | ✅ real |
| Sandboxed file tools, document/report generation | ✅ real |
| Memory with secret refusal, editing, export | ✅ real |
| Approval workflow (dashboard, WhatsApp **Approve/Reject buttons**, or reply `approve a_…` — one shared decision service and audit trail), JWT auth, encrypted token storage | ✅ real |
| PWA install, offline shell, SSE live updates | ✅ real |
| Voice input/output in the browser | ✅ real (Web Speech API, on-device) |
| Offline planner (no LLM connected) | ✅ real, clearly labelled |

## What needs your credentials (interfaces are implemented and tested for shape)

| Capability | Needs |
|---|---|
| AI-written scripts, summaries, smarter planning | `GEMINI_API_KEY` or `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` |
| Voiceover in videos | `OPENAI_API_KEY` or `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` |
| Gmail + Google Calendar | Google OAuth client (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) |
| YouTube upload + analytics | same Google client with YouTube scopes |
| Instagram Reels | Meta app (`META_APP_ID`, `META_APP_SECRET`), Business account, **public** `PUBLIC_BASE_URL` |
| WhatsApp control | Cloud API token, phone number id, app secret, verify token, allowlisted numbers |
| Local computer commands | `DESKTOP_BRIDGE_TOKEN` + running `desktop/bridge.py` |

Full setup walkthrough: [SETUP.md](SETUP.md). Architecture: [ARCHITECTURE.md](ARCHITECTURE.md).
Roadmap and remaining gaps: [TODO.md](TODO.md).

---

## The agent loop

1. **Understand** — intent is detected from the instruction (research, content, email, reminder…).
2. **Plan** — an LLM produces a validated tool plan, or the deterministic planner routes the intent.
   Unknown tool names and malformed steps are discarded.
3. **Permission check** — `safe` runs, `confirm` asks once (or is trusted), `blocked` always asks,
   and a hard deny-list exists for money/security/destructive actions.
4. **Execute** — tools run with retries; every step emits a persisted event and a live SSE event.
5. **Verify** — each tool reports whether the result was verified; tasks only show "completed" when
   the steps verified, otherwise they are flagged as unverified.
6. **Report** — dashboard notification, optional WhatsApp message, artifacts linked in the task.

Approving a gated action re-queues the exact same step and continues from where it stopped. The
decision can come from the dashboard or from the allowlisted WhatsApp number, and both go through
`services/approvals.py`, so task transitions and audit entries are identical.

---

## Project layout

```
backend/
  app/
    agent/        planner, executor, worker, orchestrator, permissions, llm providers
    api/          auth, tasks, chat, approvals, content, files, integrations, system, whatsapp, triggers…
    services/     google_api, whatsapp, media (ffmpeg), notifications, integration registry
    tools/        31 registered tools (web, files, memory, content, video, email, calendar…)
    models.py     users, tasks, events, memories, approvals, content, workflows, audit logs
  tests/          pytest: planner, permissions, webhook security, API, video render
frontend/
  app/(app)/      18 routes: dashboard, chat, tasks, studio, youtube, instagram, library,
                  research, calendar, emails, files, memories, integrations, settings,
                  permissions, logs, mobile
  components/     app shell, task/approval/content cards, UI primitives, icons
  lib/            typed API client, SSE hook, formatters
desktop/bridge.py local allowlisted command executor
docker-compose.yml  Postgres + backend + frontend
```

---

## Security posture

- Passwords: PBKDF2-SHA256 (240k rounds). Sessions: signed HS256 JWTs (12 h).
- OAuth tokens: Fernet-encrypted at rest in the `secrets` table; never returned by any endpoint.
- WhatsApp: HMAC-SHA256 signature verification is **mandatory**; unsigned webhooks are refused,
  and only allowlisted numbers are processed.
- The agent's memory API rejects credentials and financial details.
- Files are confined to `<workspace>/<user_id>`; path traversal is rejected.
- Every authenticated mutation is written to the audit log; tokens and message bodies are not.
- Rate limits on login, chat and task creation.
- Prompt injection: external text is sanitised before reaching the planner, and the agent is
  instructed to treat web/email content as data, never instructions. Tools never execute commands
  found in fetched content.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest      # 26 tests: API, agent, security, real video render
cd frontend && npx tsc --noEmit && npm run build
```

The video test renders an actual MP4, thumbnail and SRT file — if your machine can run ffmpeg, it
passes end to end.

## License notes

The bundled `backend/app/assets/fonts/Inter-Regular.ttf` is Inter (SIL Open Font License 1.1) and is
used only for rendering text into video frames and thumbnails.
