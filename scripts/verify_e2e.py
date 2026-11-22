"""End-to-end verification through the running frontend proxy (:3000)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:3000/api/proxy"
EMAIL = "verify@example.com"
PASSWORD = "verification-password-2026"

client = httpx.Client(timeout=90)


def step(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    failures = 0

    status = client.get(f"{BASE}/api/auth/status").json()
    failures += not step("auth status reachable via proxy", True, json.dumps(status))

    register = client.post(f"{BASE}/api/auth/register", json={"email": EMAIL, "password": PASSWORD, "name": "Verify"})
    if register.status_code == 400 and "closed" in register.text.lower():
        login = client.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        register = login
    if not step("owner session", register.status_code == 200, register.text[:160]):
        return 1
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    overview = client.get(f"{BASE}/api/system/overview", headers=headers)
    failures += not step(
        "dashboard overview",
        overview.status_code == 200 and "stats" in overview.json(),
        f"active={overview.json().get('stats', {}).get('active')} ai={overview.json().get('system', {}).get('ai', {}).get('provider')}",
    )
    tools = client.get(f"{BASE}/api/system/tools", headers=headers).json()["tools"]
    failures += not step("tool registry", len(tools) >= 30, f"{len(tools)} tools")

    created = client.post(
        f"{BASE}/api/tasks",
        headers=headers,
        json={"prompt": "Create a 15-second vertical video about three habits that make learning faster"},
    )
    if not step("task accepted", created.status_code == 200, created.text[:200]):
        return 1
    task = created.json()["task"]
    print(f"      ack: {created.json()['acknowledgement'][:140]}")
    print(f"      task: {task['id']} · {task['kind']} · {task['agent']}")

    deadline = time.time() + 300
    detail = task
    while time.time() < deadline:
        detail = client.get(f"{BASE}/api/tasks/{task['id']}", headers=headers).json()["task"]
        if detail["status"] in {"completed", "failed", "waiting_approval"}:
            break
        time.sleep(3)

    failures += not step("video task completed", detail["status"] == "completed", f"{detail['status']} {detail.get('error', '')[:200]}")
    artifacts = detail.get("result", {}).get("artifacts", [])
    print(f"      progress={detail['progress']} steps={[(s['tool'], s['status']) for s in detail.get('plan', [])]}")
    for artifact in artifacts:
        print(f"      artifact: {artifact.get('kind')} {artifact.get('title', '')} {artifact.get('path', '')}")

    video = next((a for a in artifacts if a.get("kind") == "video"), None)
    if video and video.get("path"):
        path = Path(video["path"])
        failures += not step(
            "mp4 rendered on disk",
            path.exists() and path.stat().st_size > 100_000,
            f"{path.name} {path.stat().st_size // 1024 if path.exists() else 0} KB",
        )
        content_id = detail["result"]["artifacts"][0].get("content_id") or ""
        items = client.get(f"{BASE}/api/content?platform=youtube", headers=headers).json()["items"]
        failures += not step("content draft saved", len(items) > 0, f"{len(items)} items")
        if items:
            asset_token = client.get(f"{BASE}/api/system/asset-token", headers=headers).json()["token"]
            streamed = client.get(f"{BASE}/api/content/{items[0]['id']}/asset", params={"t": asset_token})
            failures += not step(
                "video streams through the API",
                streamed.status_code == 200 and len(streamed.content) > 100_000,
                f"{streamed.status_code} {len(streamed.content) // 1024} KB",
            )
    else:
        failures += not step("mp4 rendered on disk", False, "no video artifact")

    reminder = client.post(
        f"{BASE}/api/tasks", headers=headers, json={"prompt": "Remind me tomorrow at 9am to review the deployment"}
    )
    reminder_task = reminder.json()["task"]
    for _ in range(40):
        state = client.get(f"{BASE}/api/tasks/{reminder_task['id']}", headers=headers).json()["task"]
        if state["status"] in {"completed", "failed"}:
            break
        time.sleep(1)
    scheduled = client.get(f"{BASE}/api/tasks?status=scheduled", headers=headers).json()["tasks"]
    failures += not step(
        "reminder scheduled", state["status"] == "completed" and len(scheduled) > 0,
        f"{len(scheduled)} scheduled; task={state['status']}",
    )

    control = client.post(f"{BASE}/api/tasks", headers=headers, json={"prompt": "show me today's completed tasks"})
    failures += not step(
        "control command answered", control.status_code == 200 and control.json()["task"]["kind"] == "control",
        control.json()["task"]["status"] if control.status_code == 200 else control.text[:120],
    )

    memory = client.post(
        f"{BASE}/api/memory", headers=headers,
        json={"title": "Verification note", "content": "Prefers short videos.", "kind": "preference"},
    )
    refused = client.post(
        f"{BASE}/api/memory", headers=headers, json={"title": "key", "content": "my api key is sk-test"}
    )
    failures += not step(
        "memory write + secret refusal",
        memory.status_code == 200 and refused.status_code == 422,
        f"{memory.status_code}/{refused.status_code}",
    )

    logs = client.get(f"{BASE}/api/system/logs", headers=headers).json()["logs"]
    failures += not step("audit log populated", len(logs) > 0, f"{len(logs)} entries")

    analytics = client.get(f"{BASE}/api/publishing/youtube/analytics", headers=headers)
    failures += not step(
        "publishing endpoint honest when unconfigured",
        analytics.status_code == 200 and analytics.json()["ok"] is False,
        analytics.json().get("detail", "")[:120],
    )

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
