# NOVA setup guide

Everything is configured with environment variables in `backend/.env`. Restart the backend after any change.

## 1. Required basics

cd backend
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into NOVA_SECRET_KEY

Variables:
- NOVA_SECRET_KEY — signs JWTs and derives encryption key for stored OAuth tokens.
- DATABASE_URL — default sqlite:///./data/nova.db; for Postgres use postgresql+psycopg2://...
- NOVA_WORKSPACE_DIR — where NOVA writes files/reports.
- PUBLIC_BASE_URL — public origin of backend (needed for Instagram/WhatsApp callback).

## 2. AI provider (optional)

Pick one; first configured key wins, or force with NOVA_AI_PROVIDER=gemini|openai|anthropic.

GEMINI_API_KEY=...  (GEMINI_MODEL=gemini-2.0-flash)
OPENAI_API_KEY=...  (OPENAI_MODEL=gpt-4o-mini)  # also enables Whisper + TTS
ANTHROPIC_API_KEY=... (ANTHROPIC_MODEL=claude-3-5-sonnet-latest)

Without a key NOVA runs the deterministic planner (real tools, no generated prose).

## 3. Google: Gmail, Calendar, YouTube

1. Google Cloud Console → new project → enable Gmail API, Google Calendar API, YouTube Data API v3, YouTube Analytics API.
2. OAuth consent screen → External → add yourself as test user.
3. Credentials → OAuth client → Web application. Redirect URI: http://localhost:8000/api/integrations/google/callback
4. Put GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env, restart, then dashboard → Integrations → Connect account.
5. For YouTube, run connect flow again from YouTube row for YouTube scopes.

## 4. WhatsApp Cloud API

1. Meta for Developers → create app → add WhatsApp product.
2. .env:
WHATSAPP_TOKEN=EAAG...
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_VERIFY_TOKEN=<random string>
WHATSAPP_APP_SECRET=<app secret>
WHATSAPP_ALLOWED_NUMBERS=+919876543210
3. Meta app → WhatsApp → Configuration: callback URL https://<backend>/api/whatsapp/webhook, verify token as above. Subscribe to messages.
4. Dashboard → Mobile: save the same number (links WhatsApp to your NOVA user).
5. Send a message from that number to control NOVA.

Webhook refuses all traffic unless WHATSAPP_APP_SECRET is set and X-Hub-Signature-256 matches. Non-allowlisted numbers dropped.

## 5. Instagram (Meta Graph API)

1. Instagram account must be Business/Creator linked to a Facebook Page.
2. Meta app → add Instagram Graph API → request instagram_content_publish.
3. .env: META_APP_ID, META_APP_SECRET, META_REDIRECT_URI=https://<backend>/api/integrations/instagram/callback
4. Set PUBLIC_BASE_URL — Meta downloads video from a public URL.
5. Dashboard → Integrations → Instagram → Connect account.

Limitations: Stories publishing and some carousel arrangements unavailable; scheduling requires media URL live when container created.

### One-click alternative (no developer apps)

Dashboard → Integrations → One-click connect → paste Upload-Post API key (free: 2 accounts, 10 uploads/month). Connect YouTube/Instagram via hosted consent screen. No .env edit needed.

## 6. Supabase (managed Postgres)

1. Create Supabase project → Settings → Database → copy connection string.
2. Set DATABASE_URL to session pooler URI with ?sslmode=require.
3. Restart backend: tables created automatically.
4. Optional Supabase Auth: set SUPABASE_JWT_SECRET.

## 7. Local desktop agent

export NOVA_BASE_URL=http://127.0.0.1:8000
export DESKTOP_BRIDGE_TOKEN=<same as backend>
export DESKTOP_ALLOWED_COMMANDS="git status,npm test,python --version"
python desktop/bridge.py

## 8. Event triggers (signed webhooks)

Create a trigger via POST /api/triggers with a prompt template. Fire events signed over raw body with X-NOVA-Signature: sha256=<hmac>. See scripts/demo_trigger.py.

## 9. Docker

cp backend/.env.example backend/.env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose up --build

Frontend :3000, backend :8000, Postgres internal. Workspace persists in nova_workspace volume.

## 10. Deployment notes

- Run behind HTTPS. WhatsApp/OAuth callbacks require public HTTPS.
- Keep backend awake for scheduled jobs/webhooks.
- Set NOVA_ENV=production and strong NOVA_SECRET_KEY.
- Back up DATABASE_URL data and NOVA_WORKSPACE_DIR.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Dashboard says credentials missing | env vars not set, or backend not restarted |
| Gmail is not connected | OAuth not completed, or refresh token revoked |
| Video has no narration | no TTS key — silent track used |
| Instagram refuses to publish | PUBLIC_BASE_URL missing or not reachable |
| WhatsApp webhook 403 | signature mismatch: check WHATSAPP_APP_SECRET |
| Tasks stay queued | worker disabled (NOVA_WORKER_ENABLED=false) or crashed |
