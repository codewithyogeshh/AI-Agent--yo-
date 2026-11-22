# NOVA — your personal autonomous AI operator

**Download:** [Source (ZIP)](https://github.com/codewithyogeshh/AI-Agent--yo-/archive/refs/heads/main.zip)

## Quick start (local)

cd backend
cp .env.example .env
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000

cd frontend
npm install
npm run dev

## Setup (minimum)

1. cd backend && cp .env.example .env
2. Generate NOVA_SECRET_KEY: python -c "import secrets; print(secrets.token_urlsafe(48))" -> paste into .env
3. Create venv + install
4. Start backend
5. Frontend: cd frontend && npm install && npm run dev
6. Open dashboard, create owner account. See SETUP.md for more.
