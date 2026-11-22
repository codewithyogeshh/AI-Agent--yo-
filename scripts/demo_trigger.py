#!/usr/bin/env python3
"""Working trigger example: an external event creates and runs a real NOVA task.

It registers a trigger whose prompt template turns a signed webhook into a
follow-up reminder, then fires it exactly as a CRM, form tool or automation
platform would — HMAC-signed body, delivery id, real task, real audit entries.

Usage:
    python scripts/demo_trigger.py --email you@example.com --password 'your-password'
    python scripts/demo_trigger.py --register --email demo@example.com --password 'demo-password-2026'

Options:
    --base      backend URL (default: $NOVA_BASE_URL or http://127.0.0.1:8000)
    --keep      leave the trigger in place instead of deleting it at the end
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

TEMPLATE = "Remind me to follow up with {{name}} about {{topic}} tomorrow at 09:00"
PAYLOAD = {"name": "Priya", "topic": "the pricing proposal", "source": "demo-crm"}


def call(base: str, path: str, payload=None, token: str = "", method: str = ""):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base.rstrip("/") + path, data=data, method=method or ("POST" if data is not None else "GET")
    )
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("NOVA_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--email", default=os.environ.get("NOVA_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("NOVA_PASSWORD", ""))
    parser.add_argument("--register", action="store_true", help="create the owner account first")
    parser.add_argument("--keep", action="store_true", help="keep the trigger after the demo")
    args = parser.parse_args()

    if not args.email or not args.password:
        parser.print_help()
        print("\nError: provide --email and --password (or NOVA_EMAIL / NOVA_PASSWORD).")
        return 2

    base = args.base
    status, body = call(base, "/api/auth/status")
    if status != 200:
        print(f"Backend not reachable at {base}: {status} {body}")
        return 1
    print(f"backend: {base} (registration_open={body.get('registration_open')})")

    if args.register:
        status, body = call(
            base, "/api/auth/register", {"email": args.email, "password": args.password, "name": "Demo"}
        )
        if status != 200:
            print(f"register failed ({status}): {body.get('detail')}")
            print("If the account exists, drop --register and log in instead.")
            return 1
        token = body["token"]
    else:
        status, body = call(base, "/api/auth/login", {"email": args.email, "password": args.password})
        if status != 200:
            print(f"login failed ({status}): {body.get('detail')}")
            return 1
        token = body["token"]
    print("authenticated")

    status, body = call(
        base,
        "/api/triggers",
        {"name": "Lead follow-up (demo)", "prompt_template": TEMPLATE, "filters": {"source": "demo-crm"}},
        token=token,
    )
    if status != 201:
        print(f"could not create trigger ({status}): {body}")
        return 1
    trigger = body["trigger"]
    print(f"trigger created: {trigger['id']}  endpoint={trigger['endpoint']}")

    raw = json.dumps(PAYLOAD).encode()
    signature = "sha256=" + hmac.new(trigger["secret"].encode(), raw, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        base + trigger["endpoint"], data=raw, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-NOVA-Signature": signature,
            "X-NOVA-Delivery": f"demo-{int(time.time())}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            fired = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"fire failed ({exc.code}): {exc.read().decode()[:300]}")
        return 1
    print(f"event accepted → task {fired['task_id']} ({fired['status']})")

    task = {}
    deadline = time.time() + 60
    while time.time() < deadline:
        status, body = call(base, f"/api/tasks/{fired['task_id']}", token=token)
        task = body.get("task", {})
        if task.get("status") in {"completed", "failed", "cancelled", "waiting_approval"}:
            break
        time.sleep(1)
    print(f"task status: {task.get('status')}")
    for event in (task.get("events") or [])[-4:]:
        print(f"  · {event['type']}: {event['message'][:110]}")

    if not args.keep:
        call(base, f"/api/triggers/{trigger['id']}", token=token, method="DELETE")
        print("trigger deleted (use --keep to keep it)")
    return 0 if task.get("status") == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
