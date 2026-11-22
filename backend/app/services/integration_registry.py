"""Single source of truth for what NOVA can connect to and how.

Status is derived from reality: env credentials present + stored tokens. A
provider is never reported as "connected" unless we hold a token for it.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Integration, Secret, User

PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "google",
        "name": "Google · Gmail + Calendar",
        "category": "Productivity",
        "env": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/calendar",
        ],
        "capabilities": ["Read/search mail", "Summarise inbox", "Draft & send mail", "Read/create calendar events"],
        "setup": [
            "Create an OAuth client (Web application) in Google Cloud Console.",
            "Enable the Gmail API and Google Calendar API.",
            f"Add redirect URI: {settings.google_redirect_uri}",
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, restart the backend, then press Connect.",
        ],
        "docs": "https://developers.google.com/identity/protocols/oauth2/web-server",
    },
    {
        "id": "youtube",
        "name": "YouTube",
        "category": "Publishing",
        "env": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        "scopes": [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
        "capabilities": ["Upload videos", "Set metadata & thumbnails", "Read channel analytics"],
        "setup": [
            "Enable YouTube Data API v3 and YouTube Analytics API in the same Google Cloud project.",
            "Complete the OAuth consent screen and add yourself as a test user while unverified.",
            "Connect Google with the YouTube scopes enabled.",
        ],
        "docs": "https://developers.google.com/youtube/v3/guides/uploading_a_video",
    },
    {
        "id": "instagram",
        "name": "Instagram (Meta Graph API)",
        "category": "Publishing",
        "env": ["META_APP_ID", "META_APP_SECRET"],
        "scopes": ["instagram_basic", "instagram_content_publish", "pages_show_list", "business_management"],
        "capabilities": ["Publish Reels (public video URL required)", "Read media insights"],
        "setup": [
            "Instagram publishing requires a Business/Creator account linked to a Facebook Page.",
            "Create a Meta app, add Instagram Graph API, and request instagram_content_publish.",
            "Set META_APP_ID / META_APP_SECRET, then complete the connect flow with the Page-linked account.",
            "Note: Stories and some carousel features are not exposed to third-party APIs — NOVA reports this instead of faking it.",
        ],
        "docs": "https://developers.facebook.com/docs/instagram-api/guides/content-publishing",
    },
    {
        "id": "whatsapp",
        "name": "WhatsApp Business Cloud API",
        "category": "Control channel",
        "env": ["WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN"],
        "scopes": ["whatsapp_business_messaging"],
        "capabilities": ["Receive instructions", "Send progress + approvals", "Voice note intake (needs transcription key)"],
        "setup": [
            "Create a Meta app with the WhatsApp product and a test/production number.",
            f"Set the webhook callback to https://<your-backend>/api/whatsapp/webhook and verify token to WHATSAPP_VERIFY_TOKEN.",
            "Set WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_APP_SECRET (signature validation).",
            "Add your own number to WHATSAPP_ALLOWED_NUMBERS — everyone else is rejected.",
        ],
        "docs": "https://developers.facebook.com/docs/whatsapp/cloud-api",
    },
]


def provider_env_present(provider: Dict[str, Any]) -> bool:
    return all(os.getenv(name) for name in provider["env"])


def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in PROVIDERS if p["id"] == provider_id), None)


def token_names(provider_id: str) -> List[str]:
    return [f"{provider_id}.access_token", f"{provider_id}.refresh_token", f"{provider_id}.expires_at"]


def has_token(db: Session, user: User, provider_id: str) -> bool:
    names = token_names(provider_id)
    row = (
        db.query(Secret)
        .filter(Secret.user_id == user.id, Secret.name.in_(names))
        .first()
    )
    return row is not None


def status_for(db: Session, user: User, provider: Dict[str, Any]) -> Dict[str, Any]:
    record = (
        db.query(Integration)
        .filter(Integration.user_id == user.id, Integration.provider == provider["id"])
        .first()
    )
    env_ok = provider_env_present(provider)
    if has_token(db, user, provider["id"]):
        status = "connected"
    elif env_ok:
        status = "needs_auth"
    else:
        status = "not_configured"
    if record and record.status == "error":
        status = "error"
    return {
        "id": provider["id"],
        "name": provider["name"],
        "category": provider["category"],
        "status": status,
        "env_configured": env_ok,
        "env": provider["env"],
        "scopes": provider["scopes"],
        "capabilities": provider["capabilities"],
        "setup": provider["setup"],
        "docs": provider["docs"],
        "last_error": record.last_error if record else "",
        "last_sync_at": record.last_sync_at.isoformat() if record and record.last_sync_at else None,
    }


def integration_status(db: Session, user: User) -> List[Dict[str, Any]]:
    return [status_for(db, user, provider) for provider in PROVIDERS]


def upsert_status(db: Session, user: User, provider_id: str, status: str, error: str = "") -> None:
    record = (
        db.query(Integration)
        .filter(Integration.user_id == user.id, Integration.provider == provider_id)
        .first()
    )
    if record is None:
        record = Integration(user_id=user.id, provider=provider_id)
        db.add(record)
    record.status = status
    record.last_error = error[:1000]
    db.commit()
