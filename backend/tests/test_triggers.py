"""Event triggers: signed webhooks must be unforgeable, idempotent and end in a
real task that runs through the normal planner/executor.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from app.db import SessionLocal
from app.models import AuditLog, Task, Trigger
from app.services import triggers as trigger_service

TEMPLATE = "Remind me to follow up with {{name}} about {{topic}} tomorrow at 09:00"


def _create(client, headers, name="Lead follow-up", template=TEMPLATE, filters=None, kind="webhook"):
    response = client.post(
        "/api/triggers",
        headers=headers,
        json={
            "name": name,
            "prompt_template": template or TEMPLATE,
            "filters": filters or {},
            "kind": kind,
        },
    )
    return response


def _signed(client, trigger, payload, secret=None, delivery=None, prefix=""):
    raw = json.dumps(payload).encode()
    key = (secret or trigger["secret"]).encode()
    signature = "sha256=" + hmac.new(key, raw, hashlib.sha256).hexdigest()
    headers = {"x-nova-signature": signature, "content-type": "application/json"}
    if delivery:
        headers["x-nova-delivery"] = delivery
    return client.post(f"{prefix}/api/triggers/{trigger['id']}/fire", content=raw, headers=headers)


def _wait(client, headers, task_id, timeout=25) -> dict:
    deadline = time.time() + timeout
    task: dict = {}
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}", headers=headers).json()["task"]
        if task["status"] in {"completed", "failed", "cancelled", "waiting_approval"}:
            return task
        time.sleep(0.25)
    raise AssertionError(f"task {task_id} did not finish: {task}")


def test_create_trigger_returns_secret_only_once(client, headers):
    response = _create(client, headers, name="Secret lifecycle")
    assert response.status_code == 201, response.text
    trigger = response.json()["trigger"]
    assert trigger["secret"] and len(trigger["secret"]) > 20
    assert trigger["endpoint"] == f"/api/triggers/{trigger['id']}/fire"

    listing = client.get("/api/triggers", headers=headers).json()["triggers"]
    row = next(item for item in listing if item["id"] == trigger["id"])
    assert "secret" not in row
    assert row["kind"] == "webhook"


def test_signed_webhook_creates_and_completes_a_task(client, headers):
    trigger = _create(client, headers, name="Lead follow-up (e2e)").json()["trigger"]

    response = _signed(
        client, trigger, {"name": "Priya", "topic": "the pricing proposal"}, delivery="delivery-1"
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] in {"queued", "planning", "completed"}

    task = _wait(client, headers, body["task_id"])
    assert task["status"] == "completed", task
    assert task["source"] == "trigger"
    assert "Priya" in task["prompt"] and "pricing proposal" in task["prompt"]

    db = SessionLocal()
    try:
        row = db.get(Trigger, trigger["id"])
        assert row.fire_count == 1
        assert row.last_fired_at is not None
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.action == "trigger.fired", AuditLog.target == trigger["id"])
            .all()
        )
        assert logs and json.loads(logs[-1].data_json)["task_id"] == body["task_id"]
    finally:
        db.close()


def test_missing_or_wrong_signature_is_rejected(client, headers):
    trigger = _create(client, headers, name="Signature check").json()["trigger"]
    raw = json.dumps({"name": "Mallory"}).encode()

    db = SessionLocal()
    try:
        before = db.query(Task).filter(Task.source == "trigger").count()
    finally:
        db.close()

    unsigned = client.post(f"/api/triggers/{trigger['id']}/fire", content=raw)
    assert unsigned.status_code == 403

    forged = client.post(
        f"/api/triggers/{trigger['id']}/fire",
        content=raw,
        headers={"x-nova-signature": "sha256=" + "0" * 64},
    )
    assert forged.status_code == 403

    db = SessionLocal()
    try:
        assert db.query(Task).filter(Task.source == "trigger").count() == before
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.action == "trigger.rejected", AuditLog.target == trigger["id"])
            .all()
        )
        assert logs and logs[-1].level == "warning"
    finally:
        db.close()


def test_disabled_trigger_does_not_fire(client, headers):
    trigger = _create(client, headers, name="Disabled trigger").json()["trigger"]
    patched = client.patch(f"/api/triggers/{trigger['id']}", headers=headers, json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["trigger"]["enabled"] is False

    response = _signed(client, trigger, {"name": "Priya", "topic": "anything"})
    assert response.status_code == 403


def test_filters_gate_events(client, headers):
    trigger = _create(
        client, headers, name="Paid orders only", filters={"status": "paid", "customer.vip": True}
    ).json()["trigger"]

    ignored = _signed(
        client, trigger, {"status": "unpaid", "customer": {"vip": True}, "name": "Sam", "topic": "x"}
    )
    assert ignored.status_code == 202
    assert ignored.json()["skipped"] == "filters"
    assert ignored.json()["task_id"] is None

    accepted = _signed(
        client,
        trigger,
        {"status": "paid", "customer": {"vip": True}, "name": "Sam", "topic": "the renewal"},
        delivery="paid-1",
    )
    assert accepted.status_code == 202
    assert accepted.json()["task_id"]

    db = SessionLocal()
    try:
        assert db.get(Trigger, trigger["id"]).fire_count == 1
    finally:
        db.close()


def test_duplicate_delivery_id_is_idempotent(client, headers):
    trigger = _create(client, headers, name="Retry safe").json()["trigger"]

    first = _signed(client, trigger, {"name": "Ana", "topic": "the invoice"}, delivery="retry-1")
    second = _signed(client, trigger, {"name": "Ana", "topic": "the invoice"}, delivery="retry-1")
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["task_id"]
    assert second.json() == {"trigger": trigger["id"], "duplicate": True, "task_id": None}

    db = SessionLocal()
    try:
        assert db.get(Trigger, trigger["id"]).fire_count == 1
    finally:
        db.close()


def test_secret_rotation_invalidates_the_old_secret(client, headers):
    trigger = _create(client, headers, name="Rotation").json()["trigger"]
    old_secret = trigger["secret"]

    rotated = client.post(f"/api/triggers/{trigger['id']}/rotate-secret", headers=headers)
    assert rotated.status_code == 200
    new_secret = rotated.json()["secret"]
    assert new_secret != old_secret

    assert _signed(client, trigger, {"name": "A", "topic": "B"}, secret=old_secret).status_code == 403
    assert _signed(client, trigger, {"name": "A", "topic": "B"}, secret=new_secret).status_code == 202


def test_unknown_trigger_returns_404_and_gmail_kind_is_explained(client, headers):
    missing = client.post("/api/triggers/tr_doesnotexist/fire", content=b"{}")
    assert missing.status_code == 404

    unsupported = _create(client, headers, kind="gmail")
    assert unsupported.status_code == 400
    assert "webhook" in unsupported.json()["detail"].lower()


def test_prompt_rendering_and_filters_are_pure_functions():
    payload = {"user": {"name": "Priya"}, "items": [{"title": "first"}], "count": 3, "paid": True}

    assert trigger_service.render_prompt("Hi {{user.name}}", payload) == "Hi Priya"
    assert trigger_service.render_prompt("{{items.0.title}}/{{count}}", payload) == "first/3"
    assert trigger_service.render_prompt("flag={{paid}}", payload) == "flag=true"
    assert trigger_service.render_prompt("missing {{nope}}!", payload) == "missing !"

    appended = trigger_service.render_prompt("No placeholders here", payload)
    assert appended.startswith("No placeholders here")
    assert "Event payload" in appended and "Priya" in appended

    assert trigger_service.matches({"user.name": "Priya", "count": 3, "paid": True}, payload)
    assert not trigger_service.matches({"user.name": "Sam"}, payload)
    assert not trigger_service.matches({"paid": False}, payload)


def test_delete_trigger_stops_deliveries(client, headers):
    trigger = _create(client, headers, name="Delete me").json()["trigger"]
    assert _signed(client, trigger, {"name": "A", "topic": "B"}, delivery="d-del").status_code == 202

    deleted = client.delete(f"/api/triggers/{trigger['id']}", headers=headers)
    assert deleted.status_code == 200
    assert _signed(client, trigger, {"name": "A", "topic": "B"}).status_code == 404
