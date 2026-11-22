# NOVA — your personal autonomous AI operator

NOVA is a self-hosted agent that plans, executes and verifies real work: web research, file production, video generation with ffmpeg, reminders, scheduling, plus approval-gated publishing to YouTube/Instagram and email/calendar via official APIs. Control it from a responsive web dashboard, an installable PWA, or WhatsApp.

**Download:** [Source (ZIP)](https://github.com/codewithyogeshh/AI-Agent--yo-/archive/refs/heads/main.zip) · [Clone](https://github.com/codewithyogeshh/AI-Agent--yo-.git)

## Quick start (local)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

New terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, create the owner account. ffmpeg missing? NOVA uses static binary from imageio-ffmpeg.

## Setup (minimum)

1. cd backend && cp .env.example .env
2. Generate NOVA_SECRET_KEY: python -c "import secrets; print(secrets.token_urlsafe(48))" and paste into .env
3. Create venv + install requirements
4. Start backend on port 8000
5. Frontend: cd frontend && npm install && npm run dev
6. Open dashboard, create owner account. Add API keys later in .env as needed.

Full setup walkthrough: [SETUP.md](SETUP.md). Architecture: [ARCHITECTURE.md](ARCHITECTURE.md).
