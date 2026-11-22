# NOVA setup guide

Everything is configured with environment variables in `backend/.env`. Restart the backend after any
change. Secrets are never read by the frontend.

## 1. Required basics

```bash
cd backend
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into NOVA_SECRET_KEY
```

| Variable | Meaning |
|---|---|
| `NOVA_SECRET_KEY` | Signs JWTs and derives the encryption key for stored OAuth tokens. Changing it invalidates sessions **and** makes stored tokens unreadable. |
| `DATABASE_URL` | Default `sqlite:///./data/nova.db`. For Postgres/Supabase use `postgresql+psycopg2://user:pass@host:5432/postgres?sslmode=require`. |
| `NOVA_WORKSPACE_DIR` | Where NOVA writes files, renders and reports. |
| `PUBLIC_BASE_URL` | Public origin of the backend (e.g. `https://nova.example.com`). Required for Instagram publishing and for the WhatsApp callback URL hint. |

## 2. AI provider (optional but recommended)

Pick one — the first configured key wins, or force with `NOVA_AI_PROVIDER=gemini|openai|anthropic`.

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash

OPENAI_API_KEY=...          # also enables Whisper transcription + TTS
OPENAI_MODEL=gpt-4o-mini

ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

Without a key NOVA runs the deterministic planner: real tools, real reports, but no generated prose.
The dashboard says "Offline planner mode" everywhere this matters.

## 3. Google: Gmail, Calendar, YouTube

1. Google Cloud Console → new project → enable **Gmail API**, **Google Calendar API**,
   **YouTube Data API v3**, **YouTube Analytics API**.
2. OAuth consent screen → External → add yourself as a test user while unverified.
3. Credentials → Create OAuth client → Web application.
   Authorised redirect URI: `http://localhost:8000/api/integrations/google/callback`
   (or `https://your-backend/api/integrations/google/callback`).
4. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`, restart, then dashboard →
   Integrations → **Connect account**. Tokens are encrypted in the `secrets` table.
5. For YouTube, run the connect flow again from the YouTube row so the YouTube scopes are granted.

## 4. WhatsApp Cloud API

1. Meta for Developers → create app → add **WhatsApp** product; get a test number or connect a
   production number.
2. `.env`:
   ```env
   WHATSAPP_TOKEN=EAAG...
   WHATSAPP_PHONE_NUMBER_ID=1234567890
   WHATSAPP_VERIFY_TOKEN=<any random string you choose>
   WHATSAPP_APP_SECRET=<app secret, used for signature validation>
   WHATSAPP_ALLOWED_NUMBERS=+919876543210
   ```
3. In the Meta app → WhatsApp → Configuration, set the callback URL to
   `https://<your-backend>/api/whatsapp/webhook` and the verify token to the value above.
   Subscribe to the `messages` field.
4. Open the dashboard → Mobile and save the same number on your account (it links WhatsApp to your
   NOVA user).
5. Send "find the latest AI news and send me a summary" from that number.
6. When a task needs approval you get an interactive message with **Approve** and **Reject**
   buttons — tap one, no ID typing needed. Typing still works too, from the same number:
   ```
   approve a_1a2b3c4d5e6f7890
   reject a_1a2b3c4d5e6f7890 - not ready to publish
   ```
   Buttons are free-form messages, so they need the 24-hour customer service window open (normally
   true, since the approval follows your own instruction). Outside that window Meta rejects them and
   NOVA falls back to a plain text message with the same ID.
   A unique prefix is enough (`approve a_1a2b`). The decision runs through the same service as the
   dashboard, so the task resumes or is cancelled identically and the audit log records
   `approval.approve` / `approval.reject` with actor `whatsapp`.

Security: the webhook refuses all traffic unless `WHATSAPP_APP_SECRET` is set and the
`X-Hub-Signature-256` matches. Non-allowlisted numbers are dropped before any processing, so an
approval reply from any other number changes nothing.

## 5. Instagram (Meta Graph API)

1. Instagram account must be **Business or Creator** and linked to a Facebook Page.
2. Meta app → add **Instagram Graph API** → request `instagram_content_publish`.
3. `.env`: `META_APP_ID`, `META_APP_SECRET`,
   `META_REDIRECT_URI=https://<your-backend>/api/integrations/instagram/callback`.
4. Set `PUBLIC_BASE_URL` — Meta downloads the video from a public URL; it cannot accept a local file.
5. Dashboard → Integrations → Instagram → Connect account.

Limitations NOVA will state outright: Stories publishing and some carousel arrangements are not
available to third-party apps; scheduling requires the media URL to be live when the container is
created.

### One-click alternative (no Google Cloud or Meta developer app)

If creating developer apps is the blocker, use managed connect: Upload-Post owns verified OAuth
apps, NOVA opens their hosted connect page, and the only step left is approving the consent screen.

1. Dashboard → **Integrations → One-click connect** → paste an Upload-Post API key
   (free plan: 2 connected accounts, 10 uploads/month; create it at app.upload-post.com → API).
   The key is validated before saving, encrypted at rest, and never displayed again.
2. Press **Connect** next to YouTube or Instagram, approve the consent screen, and return — the
   panel refreshes with the linked handle. **Disconnect** works per platform.
3. No `.env` edit and no restart are needed.

Publishing follows the link automatically: `youtube.upload` and `instagram.publish` use the managed
account when that platform is linked (no Google/Meta credentials, and Instagram no longer needs a
public media URL), and fall back to the direct APIs when it is not. Approval rules are unchanged —
publishing still waits for your approval.

Things to know:
- A **failed managed upload is not retried through the direct API** — that could double-post. Fix
  the error and retry instead.
- YouTube privacy is forwarded explicitly as `privacyStatus` (`private`/`unlisted`/`public`) —
  Upload-Post otherwise defaults to **public** — and `publish_at` is sent as `youtube_publish_at`,
  which forces a private scheduled release just like the direct API.
- Free plan = 10 uploads/month; Upload-Post returns a clear usage error when it is exhausted.
- Accounts are held by Upload-Post, so revoking access there also disconnects NOVA.

## 6. Supabase (managed Postgres)

1. Create a Supabase project → Settings → Database → copy the connection string.
2. Set `DATABASE_URL` to the **session pooler** URI with `?sslmode=require`.
3. Restart the backend: tables are created automatically (`Base.metadata.create_all`).
4. Optional Supabase Auth: set `SUPABASE_JWT_SECRET` and NOVA will accept Supabase-issued JWTs
   (audience `authenticated`) and provision the matching user row on first call.

Row Level Security note: NOVA is a single-owner application and talks to Postgres with its own
service role, so RLS policies on these tables are not required. If you expose the database to other
clients, enable RLS and scope every policy to `auth.uid()`.

## 7. Local desktop agent

```bash
export NOVA_BASE_URL=http://127.0.0.1:8000
export DESKTOP_BRIDGE_TOKEN=<same as backend>
export DESKTOP_ALLOWED_COMMANDS="git status,npm test,python --version"
python desktop/bridge.py
```

Commands must be on the allowlist both on the backend and the bridge, are executed without a shell,
and every queued command requires your approval in the dashboard first.

## 8. Event triggers (signed webhooks)

A trigger is a saved prompt template plus a secret. Any external service — CRM, form, monitoring,
Zapier/Make, or your own script — can POST a JSON event and NOVA runs a normal task: same planner,
permissions, approvals, verification and audit log as a typed instruction.

1. Create one (needs a dashboard session token):
   ```bash
   curl -s http://127.0.0.1:8000/api/triggers \
     -H "Authorization: Bearer $NOVA_TOKEN" -H "Content-Type: application/json" \
     -d '{"name":"Lead follow-up",
          "prompt_template":"Remind me to follow up with {{name}} about {{topic}} tomorrow at 09:00",
          "filters":{"source":"crm"}}'
   ```
   The response returns `secret` **once**, plus `endpoint` (and `public_endpoint` when
   `PUBLIC_BASE_URL` is set). The secret is encrypted at rest and never shown again;
   `POST /api/triggers/{id}/rotate-secret` issues a new one.

2. Send an event signed over the **raw body**:
   ```bash
   BODY='{"source":"crm","name":"Priya","topic":"the pricing proposal"}'
   SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$NOVA_TRIGGER_SECRET" -r | cut -d' ' -f1)"
   curl -s http://127.0.0.1:8000/api/triggers/tr_xxx/fire \
     -H "Content-Type: application/json" -H "X-NOVA-Signature: $SIG" \
     -H "X-NOVA-Delivery: lead-1042" -d "$BODY"
   ```
   - `{{field}}`, `{{nested.field}}`, `{{items.0.title}}` and `{{payload}}` are interpolated; a template
     with no placeholders gets the JSON payload appended.
   - `filters` is an exact-match gate — non-matching events are acknowledged and skipped.
   - `X-NOVA-Delivery` deduplicates provider retries, so one event never creates two tasks.
   - Limits: 64 KB body, 30 events/minute per trigger, signature mandatory, disabled triggers refuse.
   - Every fire is audited as `trigger.fired` (plus `trigger.rejected` for bad signatures).

3. Or run the complete example (creates trigger → signs event → waits for the task):
   ```bash
   python scripts/demo_trigger.py --email you@example.com --password 'your-password'
   ```

Gmail `users.watch` / Pub/Sub push and calendar change events reuse this table and endpoint pattern;
the pollers are the next step (see `TODO.md`).

## 9. Docker

```bash
cp backend/.env.example backend/.env      # fill in values
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose up --build
```

Frontend on `:3000`, backend on `:8000`, Postgres on the internal network. Workspace files persist in
the `nova_workspace` volume.

## 10. Deployment notes

- Run behind HTTPS (Caddy, nginx, Cloudflare Tunnel). WhatsApp and OAuth callbacks require public
  HTTPS URLs.
- Keep the backend awake for scheduled jobs/webhooks; the local machine only needs to be online for
  desktop-bridge commands.
- Set `NOVA_ENV=production` and a strong `NOVA_SECRET_KEY`.
- Back up `DATABASE_URL` data and `NOVA_WORKSPACE_DIR`; rendered videos are not reproducible without
  the source script.
- Provider billing limits are your real cost ceiling; `max_daily_tasks` and `daily_ai_budget_usd` in
  Permissions are additional guardrails.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Dashboard says "credentials missing" | env vars not set, or backend not restarted |
| `Gmail is not connected` | OAuth flow not completed, or the refresh token was revoked |
| Video has no narration | no TTS key (`OPENAI_API_KEY`/`ELEVENLABS_*`) — silent track is used |
| Instagram refuses to publish | `PUBLIC_BASE_URL` missing or not publicly reachable |
| WhatsApp webhook 403 | signature mismatch: check `WHATSAPP_APP_SECRET` |
| Trigger 403 `Invalid signature` | HMAC must be over the exact raw body (`sha256=<hex>`), not a re-serialised JSON |
| Tasks stay `queued` | worker disabled (`NOVA_WORKER_ENABLED=false`) or crashed — check `/api/system/overview` |
| `Use of the API is blocked` on YouTube | quota exhausted or app not verified for the scope |
