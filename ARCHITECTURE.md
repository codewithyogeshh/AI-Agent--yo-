# NOVA architecture

```
                    ┌─────────────────────────────┐
  WhatsApp ────────►│  FastAPI  /api/whatsapp      │
  (Cloud API,       │  signature + allowlist gate  │
   allowlisted)     └──────────────┬───────────────┘
                                   │  instruction
  Web / PWA ───────►┌──────────────▼───────────────┐
  (JWT)             │  Orchestrator                │
                    │  control commands · memory   │
                    │  context · task creation     │
                    └──────────────┬───────────────┘
                                   │ plan (steps[])
                    ┌──────────────▼───────────────┐
                    │  Planner                     │
                    │  LLM (validated tool calls)  │
                    │  or deterministic offline    │
                    └──────────────┬───────────────┘
                                   │ persisted plan_json
   ┌───────────────────────────────▼──────────────────────────────┐
   │ Worker (asyncio, N slots)                                     │
   │   claim queued → Executor                                     │
   │   Scheduler: scheduled tasks · reminders · workflows          │
   └───────────────────────────────┬──────────────────────────────┘
                                   │ per step
             ┌─────────────────────▼─────────────────────┐
             │ Executor                                  │
             │  1 permission manager   → allow/ask/deny  │
             │  2 approval gate        → waiting_approval│
             │  3 tool registry call   → retries         │
             │  4 verification flag    → honest result   │
             │  5 TaskEvent + SSE + notification         │
             └─────────────────────┬─────────────────────┘
                                   │
        ┌──────────────────────────▼───────────────────────────┐
        │ 31 tools across 9 categories                          │
        │ web · files · memory · content · video · email ·      │
        │ calendar · youtube · instagram · desktop · system     │
        └──────────────────────────┬───────────────────────────┘
                                   │
      ┌────────────────────────────▼──────────────────────────────┐
      │ Services: google_api (OAuth+Gmail+Calendar+YouTube),      │
      │ whatsapp (Cloud API), media (ffmpeg/TTS/SRT),             │
      │ notifications, integration_registry                       │
      └────────────────────────────┬──────────────────────────────┘
                                   │
             ┌─────────────────────▼─────────────────────┐
             │ Storage: SQLite (dev) or Postgres/Supabase │
             │ + workspace/<user>/ for files and renders  │
             └───────────────────────────────────────────┘
```

## Key modules

| Path | Responsibility |
|---|---|
| `backend/app/agent/planner.py` | Intent routing, LLM plan generation, tool validation, offline plans |
| `backend/app/agent/executor.py` | The only path from a plan to side effects; approvals, retries, verification |
| `backend/app/agent/permissions.py` | allow / approval / deny, trusted tools, hard deny-list, user policy |
| `backend/app/tools/base.py` | `Tool`, `ToolContext`, `ToolResult`, registry — every capability is described |
| `backend/app/agent/worker.py` | Durable claim loop, concurrency, scheduler for reminders and workflows |
| `backend/app/services/media.py` | Scene render, concat, subtitle burn-in, TTS, thumbnail — real ffmpeg |
| `backend/app/services/google_api.py` | OAuth code exchange, refresh, Gmail, Calendar |
| `backend/app/realtime.py` | In-process bus feeding SSE and WebSocket |
| `frontend/lib/api.ts` | Typed client, JWT handling, polling/SSE hooks, signed asset URLs |

## Data model (portable SQL, no dialect tricks)

`users`, `tasks`, `task_events`, `memories`, `approvals`, `integrations`, `secrets` (encrypted),
`content_items`, `media_assets`, `workflows`, `chat_messages`, `notifications`, `audit_logs`,
`user_settings`, `desktop_jobs`, `analytics_snapshots`.

- Task states: `pending → planning → queued → running → (waiting_approval) → completed | failed |
  cancelled`, plus `paused` and `scheduled`.
- `plan_json` holds the step list, each with status/output/verified/approved so a restart or an
  approval resumes exactly where it stopped.

## Adding a tool (the extension point)

```python
# backend/app/tools/mytools.py
from .base import ToolContext, ToolResult, tool

@tool(
    name="weather.today",
    description="Get today's forecast for a city.",
    category="research",
    params={"city": {"type": "string", "required": True}},
    risk="safe",            # safe | confirm | blocked
)
async def weather_today(ctx: ToolContext, city: str) -> ToolResult:
    data = await fetch_forecast(city)      # your real implementation
    return ToolResult(True, f"{city}: {data['temp']}°C", data, verified=True)
```

Register the module in `backend/app/tools/__init__.py`. It immediately becomes available to the LLM
planner, the approvals system, the audit log and the Settings → tool registry page.

## Real-time

- SSE: `GET /api/system/events?t=<jwt>` (used by the dashboard; polling fallback built in).
- WebSocket: `ws://…/ws?token=<jwt>` for native/mobile clients and the desktop bridge.
- Every event is also persisted as a `task_events` row, so the UI can replay history.

## Limits and honest constraints

- Instagram publishing requires a **public HTTPS media URL**; the Graph API cannot upload a local
  file. Without `PUBLIC_BASE_URL`, NOVA refuses and explains.
- Instagram Stories and several carousel features are not exposed to third-party APIs.
- YouTube uploads consume API quota (a full upload costs ~1600 units of the default 10k/day).
- The task queue is in-process asyncio backed by the database. That is durable across restarts but
  single-node; Redis/Celery can be swapped in behind `worker.py` for multi-node deployments.
- Voice notes on WhatsApp require an STT-capable key (OpenAI or Gemini).
