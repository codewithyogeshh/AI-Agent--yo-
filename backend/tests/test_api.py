"""End-to-end API + execution tests against a real SQLite database and worker."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path


def _wait_for(client, headers, task_id, statuses, timeout=30.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/tasks/{task_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()["task"]
        if last["status"] in statuses:
            return last
        time.sleep(0.4)
    raise AssertionError(f"Task {task_id} never reached {statuses}; last state: {last}")


def test_health_is_public(client):
    response = client.get("/api/system/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_registration_then_closed(client, auth):
    second = client.post(
        "/api/auth/register",
        json={"email": "intruder@example.com", "password": "another-long-password"},
    )
    assert second.status_code == 403


def test_login_and_profile(client, auth, headers):
    login = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "a-very-long-password"})
    assert login.status_code == 200
    me = client.get("/api/auth/me", headers=headers)
    assert me.json()["email"] == "owner@example.com"
    bad = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "nope-nope-nope"})
    assert bad.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_overview_and_tools(client, headers):
    overview = client.get("/api/system/overview", headers=headers)
    assert overview.status_code == 200
    body = overview.json()
    assert "stats" in body and "system" in body
    assert body["system"]["ai"]["provider"] == "offline"
    tools = client.get("/api/system/tools", headers=headers).json()["tools"]
    assert len(tools) >= 25
    assert any(tool["name"] == "video.produce" for tool in tools)


def test_reminder_task_executes_and_completes(client, headers):
    created = client.post(
        "/api/tasks",
        headers=headers,
        json={"prompt": "Remind me tomorrow at 9am to review the NOVA deployment"},
    )
    assert created.status_code == 200, created.text
    task = created.json()["task"]
    assert "Task received" in created.json()["acknowledgement"]

    finished = _wait_for(client, headers, task["id"], ["completed", "failed"], timeout=40)
    assert finished["status"] == "completed", finished
    assert finished["progress"] == 100
    assert finished["result"]["verified"] is True

    # The reminder materialises as a scheduled task.
    scheduled = client.get("/api/tasks?status=scheduled", headers=headers).json()["tasks"]
    assert any("review the NOVA deployment" in t["title"] for t in scheduled)


def test_control_command_pauses_tasks(client, headers):
    response = client.post("/api/tasks", headers=headers, json={"prompt": "Pause all running tasks"})
    assert response.status_code == 200
    task = response.json()["task"]
    assert task["kind"] == "control"
    assert task["status"] == "completed"


def test_approval_is_required_for_publishing(client, headers):
    # A content item + publish request must sit in waiting_approval, never publish itself.
    draft = client.post(
        "/api/content",
        headers=headers,
        json={"platform": "youtube", "title": "Test upload", "kind": "short"},
    )
    item = draft.json()["item"]
    publish = client.post(f"/api/content/{item['id']}/publish", headers=headers, json={"privacy": "private"})
    assert publish.status_code == 422  # no rendered asset yet -> honest refusal

    from app.agent.executor import execute_task
    from app.db import SessionLocal
    from app.models import Approval, Task, User

    db = SessionLocal()
    try:
        user = db.query(User).first()
        task = Task(
            user_id=user.id,
            title="Approval gate check",
            prompt="send an email",
            kind="email",
            status="queued",
            plan_json='[{"tool": "email.send", "args": {"to": "a@b.c", "subject": "s", "body": "b"}, "label": "Send mail", "status": "pending", "index": 0}]',
        )
        db.add(task)
        db.commit()
        state = asyncio.run(execute_task(task.id))
        db.refresh(task)
        assert state == "waiting_approval"
        assert task.status == "waiting_approval"
        approval = db.query(Approval).filter(Approval.task_id == task.id).first()
        assert approval is not None and approval.tool == "email.send"
    finally:
        db.close()

    pending = client.get("/api/approvals", headers=headers).json()["approvals"]
    assert pending
    decided = client.post(
        f"/api/approvals/{pending[0]['id']}/decide",
        headers=headers,
        json={"approve": False, "note": "not today"},
    )
    assert decided.status_code == 200
    assert decided.json()["task"]["status"] == "cancelled"


def test_memory_crud_and_secret_refusal(client, headers):
    created = client.post(
        "/api/memory",
        headers=headers,
        json={"title": "Video style", "content": "Prefers vertical shorts with burned-in captions.", "kind": "preference"},
    )
    assert created.status_code == 200
    memory_id = created.json()["memory"]["id"]
    listed = client.get("/api/memory?q=captions", headers=headers).json()["memories"]
    assert any(m["id"] == memory_id for m in listed)
    refused = client.post(
        "/api/memory", headers=headers, json={"title": "Key", "content": "my api key is sk-live-123"}
    )
    assert refused.status_code == 422
    assert client.delete(f"/api/memory/{memory_id}", headers=headers).json()["ok"] is True


def test_unauthenticated_access_is_rejected(client):
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/system/overview").status_code == 401


def test_whatsapp_webhook_rejects_bad_signature(client):
    response = client.post(
        "/api/whatsapp/webhook",
        content=b'{"entry":[]}',
        headers={"x-hub-signature-256": "sha256=bad"},
    )
    assert response.status_code == 403


def test_whatsapp_webhook_accepts_valid_signature(client):
    import hashlib
    import hmac

    body = b'{"entry":[]}'
    signature = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"x-hub-signature-256": signature, "content-type": "application/json"},
    )
    assert response.status_code == 200


def test_video_pipeline_renders_real_files(client, headers):
    """The production pipeline must emit an MP4, subtitles, thumbnail and metadata."""
    from app.db import SessionLocal
    from app.models import User
    from app.tools.base import ToolContext
    from app.tools.content import video_produce

    db = SessionLocal()
    try:
        user = db.query(User).first()
        events = []
        ctx = ToolContext(db=db, user=user, task=None, emit=lambda *args: events.append(args))
        ctx.state = {}
        result = asyncio.run(
            video_produce(ctx, topic="Three habits that make learning faster", platform="youtube", format="vertical", duration=15)
        )
        assert result.ok, result.summary
        data = result.data
        video = Path(data["dir"]) / "final.mp4"
        thumb = Path(data["dir"]) / "thumbnail.png"
        srt = Path(data["dir"]) / "captions.srt"
        assert srt.exists() and srt.stat().st_size > 20
        assert thumb.exists() and thumb.stat().st_size > 1000
        assert video.exists() and video.stat().st_size > 10000, result.data.get("notes")
        assert data["content_id"].startswith("c_")
        # subtitle timing must be monotonic
        lines = srt.read_text().strip().split("\n\n")
        assert lines[0].startswith("1\n")
    finally:
        db.close()
