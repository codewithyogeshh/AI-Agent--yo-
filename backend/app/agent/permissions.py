"""Permission manager.

Three outcomes: allow, approval, deny. Defaults are conservative; users can
auto-approve specific tools but irreversible actions can never be auto-approved.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from ..models import User, UserSetting

# Actions NOVA will never take autonomously, regardless of configuration.
ALWAYS_APPROVAL = {"email.send", "youtube.upload", "instagram.publish", "desktop.run", "content.publish"}
NEVER_ALLOWED = {"payments.transfer", "purchases.buy", "account.security.change", "secrets.reveal"}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_approve": [],  # tool names the user trusts for unattended runs
    "disabled_tools": [],
    "publishing_mode": "approval",  # draft | approval | auto
    "max_daily_tasks": 40,
    "daily_ai_budget_usd": 2.0,
    "notify_on_complete": True,
    "whatsapp_notifications": True,
    "research_depth": "standard",
    "voice_enabled": True,
    "default_video_format": "vertical",
    "default_language": "en",
    "allowed_dirs": [],
}


def get_settings_map(db: Session, user: User) -> Dict[str, Any]:
    values = dict(DEFAULT_SETTINGS)
    for row in db.query(UserSetting).filter(UserSetting.user_id == user.id).all():
        try:
            values[row.key] = json.loads(row.value_json)
        except json.JSONDecodeError:
            values[row.key] = row.value_json
    return values


def put_setting(db: Session, user: User, key: str, value: Any) -> Dict[str, Any]:
    row = db.query(UserSetting).filter(UserSetting.user_id == user.id, UserSetting.key == key).first()
    if row is None:
        row = UserSetting(user_id=user.id, key=key)
        db.add(row)
    row.value_json = json.dumps(value)
    db.commit()
    return get_settings_map(db, user)


def evaluate(db: Session, user: User, tool_name: str, risk: str) -> str:
    """Return 'allow' | 'approval' | 'deny'."""
    if tool_name in NEVER_ALLOWED:
        return "deny"
    prefs = get_settings_map(db, user)
    disabled: List[str] = prefs.get("disabled_tools") or []
    if tool_name in disabled:
        return "deny"
    if tool_name in ALWAYS_APPROVAL or risk == "blocked":
        return "approval"
    auto: List[str] = prefs.get("auto_approve") or []
    if risk == "confirm" and tool_name not in auto:
        return "approval"
    return "allow"


def publishing_mode(db: Session, user: User) -> str:
    return get_settings_map(db, user).get("publishing_mode", "approval")


def can_publish_automatically(db: Session, user: User) -> bool:
    return publishing_mode(db, user) == "auto"
