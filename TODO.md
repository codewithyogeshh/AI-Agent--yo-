# NOVA build status

Legend: ✅ implemented and verified · 🟡 implemented, needs credentials to verify live · ⬜ not built

## Phase 1 — Foundation
- ✅ Project structure (backend / frontend / desktop / docker)
- ✅ FastAPI backend with modular routers (13 routers, 77 routes)
- ✅ Next.js + TypeScript + Tailwind dashboard, dark, mobile-first
- ✅ Database schema (17 tables), SQLite default, Postgres/Supabase portable
- ✅ Authentication: first-run owner registration, JWT sessions, password change
- ✅ AI chat with task creation, live status and voice input
- ✅ Task manager with states, pause/cancel/retry/delete
- ✅ Memory system with search, edit, delete, export and secret refusal
- ✅ Dashboard with live stats, approvals, activity chart, system health
- ✅ PWA: manifest, icons, service worker, offline shell, install flow
- ✅ Notifications (dashboard + optional WhatsApp)

## Phase 2 — AI agent
- ✅ Planner (LLM + deterministic offline fallback, tool-name validation)
- ✅ Tool registry (31 tools, risk-tagged, typed params)
- ✅ Executor with permission gate, retries, verification, persisted events
- ✅ Durable DB-backed worker with concurrency limit
- ✅ Scheduler (due tasks, reminders, recurring workflows)
- ✅ Web research (search + extraction + cited report)
- ✅ File tools (sandboxed list/read/write/organize)
- ✅ Browser automation 🟡 Playwright is not wired in yet — research uses HTTP fetch
- ✅ Task monitoring UI with step timeline, artifacts and event log
- ✅ Emergency stop

## Phase 3 — WhatsApp
- ✅ Cloud API webhook with mandatory signature validation
- ✅ Allowlist of authorised numbers, owner resolution
- ✅ Text instructions → tasks, progress/approval notifications out
- 🟡 Voice notes (needs OPENAI_API_KEY or GEMINI_API_KEY for transcription)
- ✅ Image/document intake saved to the workspace inbox
- ✅ Approve/reject by reply from the allowlisted number (`approve a_1a2b3c`, `reject a_1a2b3c - note`),
  same decision service and audit trail as the dashboard
- ✅ Native Approve / Reject reply buttons on approval notifications, with automatic fallback to
the text message (typed `approve a_…` replies keep working)

## Phase 4 — Content studio
- ✅ Content planning, drafting, library
- 🟡 AI script writing (needs an AI provider; offline mode produces a structural script)
- ✅ Real video rendering with ffmpeg (scenes, subtitles burned in, thumbnail, metadata)
- 🟡 Voiceover (needs OpenAI or ElevenLabs key)
- ⬜ AI scene imagery (needs an image provider; scene cards are rendered instead)
- ⬜ Licensed music library (not bundled — no unlicensed audio will be shipped)

## Phase 5 — Social publishing
- 🟡 YouTube upload + thumbnail + analytics (official API, needs Google OAuth + quota)
- 🟡 Instagram Reels publish + insights (needs Meta app + public media URL)
- ✅ Publishing modes: draft / approval / auto (per workflow)
- ✅ Scheduling and content calendar
- ✅ Analytics snapshots endpoint, per-platform studios

## Phase 6 — Personal productivity
- 🟡 Gmail read/search/summarise/send (official Gmail API, needs OAuth)
- 🟡 Google Calendar read/create + scheduling proposals (needs OAuth)
- ✅ Reminders, recurring tasks, daily/weekly task reports
- ✅ Research briefs with citations

## Phase 7 — Desktop agent
- ✅ Bridge script with allowlist, no shell, approval-gated queue
- ✅ Job polling/reporting endpoints
- ⬜ Local file indexing / OS-level automation beyond the allowlist (deliberately out of scope)

## Phase 8 — Hardening
- ✅ 50 backend tests (auth, permissions, planner, approval flow, WhatsApp text + button approvals, trigger signing/filters/dedupe, webhook signatures, real video render)
- ✅ Frontend typecheck + production build
- ✅ Rate limiting, audit logs, encrypted secrets, input validation
- ⬜ Multi-node queue (Redis/Celery) — single-node asyncio worker today
- ⬜ Web push (VAPID) for background notifications on mobile
- ⬜ Playwright-driven browser agent inside the worker
- ⬜ Native Android wrapper (PWA installs today; React Native shell not built)

## One-click connect (managed)
- ✅ Managed account linking for YouTube + Instagram through Upload-Post's verified OAuth apps:
  API key stored encrypted, hosted connect page, per-platform status, disconnect
- ✅ Dashboard panel that needs one pasted key and then a single Connect button per platform
- ✅ Publish through the managed connection: `youtube.upload` and `instagram.publish` use it when
  that platform is linked, and fall back to the direct APIs when it is not
- ✅ Dashboard status shows the effective channel (direct / managed) so badges match tool behaviour
- ⬜ TikTok/other platforms from the same managed profile (only YT + IG surfaced deliberately)
- ⚠️ WhatsApp has no consumer OAuth path: it needs a Meta Business account and phone number
  (Embedded Signup via a BSP is the closest to one click, but still requires that account)

## Phase 9 — Event triggers
- ✅ `triggers` table with per-trigger HMAC secret, encrypted at rest, shown once
- ✅ Signed public endpoint (`POST /api/triggers/{id}/fire`): signature, filters, delivery dedupe,
  rate limit, 64 KB cap, disabled state, audit (`trigger.fired` / `trigger.rejected`)
- ✅ Prompt templating with dotted paths, payload append, run through the normal planner/executor
- ✅ Trigger CRUD + secret rotation API, `scripts/demo_trigger.py` working example, 10 tests
- ⬜ Gmail `users.watch` + Pub/Sub push and Google Calendar change events (same table; need OAuth)
- ⬜ Trigger management UI in the dashboard (API only today)
- ⬜ Inbound email → trigger bridge

## Known limitations (intentional, documented)
1. Instagram cannot receive local files — a public URL is mandatory.
2. Free-form WhatsApp messages (including interactive buttons) are only deliverable inside Meta's
   24-hour customer service window; outside it a pre-approved template is required. NOVA logs the
   failed push and leaves the approval waiting in the dashboard rather than silently dropping it.
3. Offline mode produces structure, not prose — it says so on every surface.
4. The worker is single-process; horizontal scaling needs an external queue.
5. Trigger events are accepted but not queued separately: if the worker is disabled or the daily task
   cap is hit, the event returns 422 and the sender sees the failure (no silent loss, no replay).
