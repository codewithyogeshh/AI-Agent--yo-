#!/usr/bin/env python3
"""NOVA desktop bridge.

Runs on your own machine and executes only allowlisted commands that NOVA has
queued *and* that you approved in the dashboard. It long-polls the backend; it
never exposes a shell and never accepts arbitrary input from the network.

Usage:
    export NOVA_BASE_URL=https://your-nova-backend
    export DESKTOP_BRIDGE_TOKEN=<same token as the backend>
    export DESKTOP_ALLOWED_COMMANDS="git status,npm test,python --version"
    python bridge.py
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = os.getenv("NOVA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.getenv("DESKTOP_BRIDGE_TOKEN", "")
ALLOWED = [item.strip() for item in os.getenv("DESKTOP_ALLOWED_COMMANDS", "").split(",") if item.strip()]
ROOT = Path(os.getenv("DESKTOP_WORKSPACE", Path.cwd())).expanduser().resolve()
TIMEOUT = int(os.getenv("DESKTOP_JOB_TIMEOUT", "300"))

BLOCKED_CHARS = set(";&|`$><\n")


def allowed(command: str) -> bool:
    if any(char in command for char in BLOCKED_CHARS):
        return False
    return any(command == prefix or command.startswith(prefix + " ") for prefix in ALLOWED)


def inside_root(cwd: str) -> Path:
    target = (ROOT / cwd).resolve() if cwd else ROOT
    if ROOT not in target.parents and target != ROOT:
        raise ValueError("working directory escapes the bridge workspace")
    return target


def run(command: str, cwd: str) -> tuple[str, int]:
    if not allowed(command):
        return (f"Refused: '{command}' is not allowlisted on this machine.", 126)
    try:
        workdir = inside_root(cwd)
    except ValueError as exc:
        return (str(exc), 126)
    try:
        # No shell: the command is parsed into argv directly.
        completed = subprocess.run(
            shlex.split(command),
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            shell=False,
        )
        output = (completed.stdout + ("\n" + completed.stderr if completed.stderr else "")).strip()
        return (output[-20000:], completed.returncode)
    except subprocess.TimeoutExpired:
        return (f"Command timed out after {TIMEOUT}s", 124)
    except FileNotFoundError:
        return (f"Executable not found for: {command}", 127)
    except Exception as exc:  # noqa: BLE001
        return (f"Bridge error: {exc}", 1)


def main() -> int:
    if not TOKEN:
        print("DESKTOP_BRIDGE_TOKEN is required", file=sys.stderr)
        return 2
    if not ALLOWED:
        print("DESKTOP_ALLOWED_COMMANDS is empty — nothing can run", file=sys.stderr)
        return 2
    print(f"NOVA bridge connected to {BASE} · workspace {ROOT} · {len(ALLOWED)} allowlisted commands")
    headers = {"X-Bridge-Token": TOKEN}
    with httpx.Client(timeout=40) as client:
        while True:
            try:
                response = client.get(f"{BASE}/api/desktop/poll", headers=headers)
                if response.status_code == 401:
                    print("Bridge token rejected by the backend", file=sys.stderr)
                    return 3
                response.raise_for_status()
                job = response.json().get("job")
                if job:
                    print(f"→ {job['command']}")
                    output, code = run(job["command"], job.get("cwd", ""))
                    client.post(
                        f"{BASE}/api/desktop/report",
                        headers=headers,
                        json={"job_id": job["id"], "output": output, "exit_code": code},
                    )
                    print(f"← exit {code}")
                else:
                    time.sleep(3)
            except httpx.HTTPError as exc:
                print(f"connection problem: {exc}; retrying in 10s", file=sys.stderr)
                time.sleep(10)
            except KeyboardInterrupt:
                print("\nbridge stopped")
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
