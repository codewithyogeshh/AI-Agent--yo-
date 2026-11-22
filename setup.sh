#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Backend
cd backend
if [ ! -f .env ]; then
  cp .env.example .env
  KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  # Replace the placeholder secret key
  python3 - "$KEY" <<'PY'
import re, sys
key = sys.argv[1]
p = ".env"
s = open(p).read()
s = s.replace("NOVA_SECRET_KEY=change-me-in-production", f"NOVA_SECRET_KEY={key}")
open(p, "w").write(s)
PY
  echo "Generated NOVA_SECRET_KEY in backend/.env"
fi

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Frontend
cd ../frontend
npm install

echo ""
echo "Setup complete."
echo "Start backend:  cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000"
echo "Start frontend: cd frontend && npm run dev   (http://localhost:3000)"
