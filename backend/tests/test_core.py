"""Unit tests for the agent core: planning, permissions, parsing, webhook security."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest


def test_offline_planner_routes_research():
    from app.agent.planner import offline_plan

    plan = offline_plan("Find the latest AI news and send me a summary")
    assert plan.kind == "research"
    assert plan.steps[0]["tool"] == "web.search"
    assert any(step["tool"] == "research.report" for step in plan.steps)
    assert all("status" in step for step in plan.steps)


def test_offline_planner_routes_video_and_publishing():
    from app.agent.planner import offline_plan

    plan = offline_plan("Create a 60-second Reel about Java programming for Instagram")
    tools = [step["tool"] for step in plan.steps]
    assert "video.produce" in tools
    assert "content.draft" in tools


def test_intent_detection_prefers_specific_intent():
    from app.agent.planner import detect_intent

    assert detect_intent("upload this video to YouTube") == "youtube_upload"
    assert detect_intent("check my emails and summarize important messages") == "email"
    assert detect_intent("create a reminder for tomorrow at 9 am") == "reminder"


def test_plan_is_valid_json_roundtrip():
    from app.agent.planner import offline_plan

    plan = offline_plan("Research vector databases")
    payload = json.loads(json.dumps(plan.steps))
    assert isinstance(payload, list) and payload


def test_permissions_defaults_are_conservative():
    from app.agent import permissions
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).first()
        assert permissions.evaluate(db, user, "email.send", "blocked") == "approval"
        assert permissions.evaluate(db, user, "files.list", "safe") == "allow"
        assert permissions.evaluate(db, user, "files.organize", "confirm") == "approval"
        # auto-approving a confirm tool works, but never for irreversible ones
        permissions.put_setting(db, user, "auto_approve", ["files.organize", "email.send"])
        assert permissions.evaluate(db, user, "files.organize", "confirm") == "allow"
        assert permissions.evaluate(db, user, "email.send", "blocked") == "approval"
        assert permissions.evaluate(db, user, "payments.transfer", "blocked") == "deny"
    finally:
        db.close()


def test_reminder_time_parsing():
    from app.tools.memory import parse_when

    tomorrow = parse_when("remind me tomorrow at 9am to stretch")
    assert tomorrow is not None
    relative = parse_when("remind me in 2 hours to check the build")
    assert relative is not None
    assert parse_when("no time mentioned here") is None


def test_sensitive_memory_is_refused():
    from app.tools.memory import _looks_sensitive

    assert _looks_sensitive("my api key is sk-123")
    assert _looks_sensitive("password: hunter2")
    assert not _looks_sensitive("I prefer short videos with captions")


def test_whatsapp_signature_validation():
    from app.security import verify_whatsapp_signature

    body = b'{"entry":[]}'
    signature = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    assert verify_whatsapp_signature(body, signature)
    assert not verify_whatsapp_signature(body, "sha256=deadbeef")
    assert not verify_whatsapp_signature(body, "")


def test_password_hashing_roundtrip():
    from app.security import hash_password, verify_password

    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)


def test_whatsapp_allowlist_normalises_numbers():
    from app.services import whatsapp

    assert whatsapp.is_allowed("+91 99999 99999")
    assert not whatsapp.is_allowed("+911111111111")


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("stop everything now", "stop_all"),
        ("pause all running tasks", "pause_all"),
        ("resume all tasks", "resume_all"),
        ("cancel task t_abcd1234", "cancel_task"),
    ],
)
def test_control_command_detection(prompt, expected):
    from app.agent.orchestrator import _control

    assert _control(prompt) == expected
