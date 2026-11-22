"""Approval replies over WhatsApp must apply the same transitions and audit trail
as the dashboard, and must only accept allowlisted senders.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import List, Tuple

from app.db import SessionLocal
from app.models import Approval, AuditLog, Notification, Task, User
from app.services import whatsapp

SENDER = "919999999999"
BLOCKED_SENDER = "911111111111"
PLAN = json.dumps(
    [
        {
            "tool": "email.send",
            "args": {"to": "a@b.c", "subject": "s", "body": "b"},
            "label": "Send the email",
            "status": "pending",
            "index": 0,
        }
    ]
)


def _signed_post(client, text: str, sender: str = SENDER):
    message = {
        "from": sender,
        "id": f"wamid.{abs(hash(text)) % 10**8}",
        "type": "text",
        "timestamp": "1700000000",
        "text": {"body": text},
    }
    return _signed_message(client, message, sender)


def _button_message(button_id: str, title: str = "Approve", sender: str = SENDER) -> dict:
    return {
        "from": sender,
        "id": f"wamid.btn{abs(hash(button_id)) % 10**8}",
        "type": "interactive",
        "timestamp": "1700000000",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": button_id, "title": title},
        },
    }


def _signed_message(client, message: dict, sender: str = SENDER):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": sender, "profile": {"name": "Owner"}}],
                            "messages": [message],
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
    return client.post(
        "/api/whatsapp/webhook",
        content=raw,
        headers={"x-hub-signature-256": signature, "content-type": "application/json"},
    )


def _make_pending(title: str = "Send the status email") -> Tuple[str, str]:
    from app.agent.executor import execute_task

    db = SessionLocal()
    try:
        user = db.query(User).first()
        task = Task(
            user_id=user.id,
            title=title,
            prompt="send an email",
            kind="email",
            status="queued",
            plan_json=PLAN,
        )
        db.add(task)
        db.commit()
        state = asyncio.run(execute_task(task.id))
        db.refresh(task)
        approval = (
            db.query(Approval)
            .filter(Approval.task_id == task.id, Approval.status == "pending")
            .first()
        )
        assert state == "waiting_approval", state
        assert approval is not None
        return approval.id, task.id
    finally:
        db.close()


def _capture_sends(monkeypatch) -> List[Tuple[str, str]]:
    sent: List[Tuple[str, str]] = []

    async def fake_send(to: str, body: str):
        sent.append((to, body))
        return {"messages": [{"id": "test"}]}

    monkeypatch.setattr(whatsapp, "send_text", fake_send)
    return sent


def test_approval_id_is_included_in_whatsapp_notification(client, auth):
    db = SessionLocal()
    try:
        approval_id, _ = _make_pending("Notify with the approval id")
        notes = [
            row.body
            for row in db.query(Notification).order_by(Notification.created_at.desc()).limit(8)
        ]
        assert any(approval_id in body for body in notes), notes
        assert any("approve" in body for body in notes)
    finally:
        db.close()


def _set_owner_phone(phone: str) -> str:
    db = SessionLocal()
    try:
        user = db.query(User).first()
        previous = user.phone
        user.phone = phone
        db.commit()
        return previous
    finally:
        db.close()


def test_approval_notification_offers_approve_and_reject_buttons(client, auth, monkeypatch):
    button_sends = []
    text_sends = []

    async def fake_buttons(to, body, buttons, footer=""):
        button_sends.append({"to": to, "body": body, "buttons": buttons, "footer": footer})
        return {"messages": [{"id": "btn"}]}

    async def fake_text(to, body):
        text_sends.append((to, body))
        return {"messages": [{"id": "txt"}]}

    monkeypatch.setattr(whatsapp, "send_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "send_text", fake_text)

    previous = _set_owner_phone("+919999999999")
    try:
        approval_id, _ = _make_pending("Send the button approval email")
    finally:
        _set_owner_phone(previous)

    assert button_sends, "approval notification must use interactive buttons"
    sent = button_sends[-1]
    assert [b["id"] for b in sent["buttons"]] == [f"approve:{approval_id}", f"reject:{approval_id}"]
    assert [b["title"] for b in sent["buttons"]] == ["Approve", "Reject"]
    assert approval_id in sent["body"]
    assert len(sent["body"]) <= 1024
    # Buttons carry the decision, so no plain-text duplicate for this notification.
    assert text_sends == []


def test_button_payload_matches_cloud_api_contract():
    payload = whatsapp.button_payload(
        "919999999999",
        "x" * 2000,
        [
            {"id": "approve:a_1a2b3c", "title": "Approve"},
            {"id": "reject:a_1a2b3c", "title": "Reject this because it is far too long"},
            {"id": "third:1", "title": "Third"},
            {"id": "fourth:1", "title": "Fourth"},
        ],
        footer="NOVA",
    )
    assert payload["type"] == "interactive"
    interactive = payload["interactive"]
    assert interactive["type"] == "button"
    assert len(interactive["body"]["text"]) == 1024
    buttons = interactive["action"]["buttons"]
    assert len(buttons) == 3  # Cloud API maximum
    assert buttons[0] == {"type": "reply", "reply": {"id": "approve:a_1a2b3c", "title": "Approve"}}
    assert all(b["type"] == "reply" for b in buttons)
    assert all(len(b["reply"]["title"]) <= 20 for b in buttons)
    assert interactive["footer"]["text"] == "NOVA"


def test_button_tap_approves_with_same_audit_trail(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, task_id = _make_pending("Send the tapped email")

    response = _signed_message(client, _button_message(f"approve:{approval_id}"))
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "approved"
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "approval.approve", AuditLog.target == approval_id)
            .all()
        )
        assert entries and entries[-1].actor == "whatsapp"
        assert json.loads(entries[-1].data_json)["channel"] == "whatsapp"
        assert db.get(Task, task_id).status != "waiting_approval"
    finally:
        db.close()
    assert any("Approved" in message for _, message in sent)


def test_button_tap_rejects(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, task_id = _make_pending("Send the rejected tap email")

    response = _signed_message(client, _button_message(f"reject:{approval_id}", title="Reject"))
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "rejected"
        assert db.get(Task, task_id).status == "cancelled"
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "approval.reject", AuditLog.target == approval_id)
            .all()
        )
        assert entries and entries[-1].actor == "whatsapp"
    finally:
        db.close()
    assert any("Rejected" in message for _, message in sent)


def test_second_tap_on_a_decided_approval_changes_nothing(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, _ = _make_pending("Send the double tap email")

    assert _signed_message(client, _button_message(f"reject:{approval_id}")).status_code == 200
    assert _signed_message(client, _button_message(f"approve:{approval_id}")).status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "rejected"
    finally:
        db.close()
    assert any("No pending approval matches" in message for _, message in sent)


def test_unknown_button_payload_is_rejected(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, _ = _make_pending("Send the unknown button email")

    response = _signed_message(client, _button_message("something:else"))
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "pending"
    finally:
        db.close()
    assert any("not recognised" in message for _, message in sent)


def test_approve_from_whatsapp_resumes_task_with_audit(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, task_id = _make_pending("Send the weekly report email")

    response = _signed_post(client, f"approve {approval_id}")
    assert response.status_code == 200

    db = SessionLocal()
    try:
        approval = db.get(Approval, approval_id)
        task = db.get(Task, task_id)
        assert approval.status == "approved"
        assert approval.decided_at is not None
        # email.send has no Google credentials, so the resumed task fails honestly.
        assert task.status in {"queued", "running", "failed"}
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "approval.approve", AuditLog.target == approval_id)
            .all()
        )
        assert entries, "approval.approve must be audited"
        assert entries[-1].actor == "whatsapp"
        assert json.loads(entries[-1].data_json)["channel"] == "whatsapp"
        assert task.status != "waiting_approval"
    finally:
        db.close()

    assert any("Approved" in message and approval_id in message for _, message in sent)


def test_reject_from_whatsapp_cancels_task_with_audit(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, task_id = _make_pending("Send the invoice email")

    response = _signed_post(client, f"reject {approval_id} — not ready")
    assert response.status_code == 200

    db = SessionLocal()
    try:
        approval = db.get(Approval, approval_id)
        task = db.get(Task, task_id)
        assert approval.status == "rejected"
        assert "not ready" in approval.note
        assert task.status == "cancelled"
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "approval.reject", AuditLog.target == approval_id)
            .all()
        )
        assert entries and entries[-1].actor == "whatsapp"
    finally:
        db.close()

    assert any("Rejected" in message for _, message in sent)


def test_short_id_prefix_resolves_the_approval(client, auth, monkeypatch):
    _capture_sends(monkeypatch)
    approval_id, _ = _make_pending("Send the prefix test email")
    prefix = approval_id[:7]

    response = _signed_post(client, f"APPROVE {prefix}")
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "approved"
    finally:
        db.close()


def test_unknown_reference_changes_nothing(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, _ = _make_pending("Send the unknown-reference email")

    response = _signed_post(client, "approve a_deadbeef1234")
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "pending"
    finally:
        db.close()
    assert any("No pending approval matches" in message for _, message in sent)


def test_bare_approve_asks_for_the_id(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, _ = _make_pending("Send the bare-approve email")

    response = _signed_post(client, "approve")
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "pending"
    finally:
        db.close()
    assert any("Which approval?" in message for _, message in sent)


def test_non_allowlisted_number_cannot_approve(client, auth, monkeypatch):
    sent = _capture_sends(monkeypatch)
    approval_id, _ = _make_pending("Send the unauthorised email")

    response = _signed_post(client, f"approve {approval_id}", sender=BLOCKED_SENDER)
    assert response.status_code == 200  # acknowledged, then dropped

    db = SessionLocal()
    try:
        assert db.get(Approval, approval_id).status == "pending"
    finally:
        db.close()
    assert sent == []


def test_dashboard_decision_still_works_and_is_audited(client, auth, headers):
    approval_id, task_id = _make_pending("Send the dashboard email")

    response = client.post(
        f"/api/approvals/{approval_id}/decide",
        headers=headers,
        json={"approve": False, "note": "handled in the dashboard"},
    )
    assert response.status_code == 200
    assert response.json()["task"]["status"] == "cancelled"

    db = SessionLocal()
    try:
        entries = (
            db.query(AuditLog)
            .filter(AuditLog.action == "approval.reject", AuditLog.target == approval_id)
            .all()
        )
        assert entries and entries[-1].actor == "dashboard"
    finally:
        db.close()
