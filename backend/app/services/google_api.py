"""Google API client (Gmail, Calendar, YouTube) with real OAuth token handling.

Tokens are encrypted at rest and refreshed automatically. Nothing here is called
unless the user has completed the OAuth flow, and every failure is surfaced.
"""
from __future__ import annotations

import base64
import json
import time
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Secret, User
from ..security import decrypt_value, encrypt_value

AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = {
    "google": [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/calendar",
    ],
    "youtube": [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ],
}


def configured(provider: str = "google") -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def auth_url(provider: str = "google", state: str = "") -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "scope": " ".join(SCOPES.get(provider, SCOPES["google"])),
        "state": state or provider,
    }
    return f"{AUTH_BASE}?{urlencode(params)}"


def _store(db: Session, user: User, name: str, value: str) -> None:
    row = db.query(Secret).filter(Secret.user_id == user.id, Secret.name == name).first()
    if row is None:
        row = Secret(user_id=user.id, name=name)
        db.add(row)
    row.ciphertext = encrypt_value(value)
    db.commit()


def _read(db: Session, user: User, name: str) -> str:
    row = db.query(Secret).filter(Secret.user_id == user.id, Secret.name == name).first()
    return decrypt_value(row.ciphertext) if row else ""


async def exchange_code(db: Session, user: User, code: str, provider: str = "google") -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        res.raise_for_status()
        tokens = res.json()
    _store(db, user, f"{provider}.access_token", tokens.get("access_token", ""))
    if tokens.get("refresh_token"):
        _store(db, user, f"{provider}.refresh_token", tokens["refresh_token"])
    expires_at = str(int(time.time()) + int(tokens.get("expires_in", 3600)) - 60)
    _store(db, user, f"{provider}.expires_at", expires_at)
    return tokens


async def access_token(db: Session, user: User, provider: str = "google") -> Optional[str]:
    token = _read(db, user, f"{provider}.access_token")
    expires = _read(db, user, f"{provider}.expires_at")
    if token and expires and expires.isdigit() and int(expires) > int(time.time()):
        return token
    refresh = _read(db, user, f"{provider}.refresh_token")
    if not refresh:
        return token or None
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if res.status_code >= 400:
            return None
        data = res.json()
    new_token = data.get("access_token", "")
    _store(db, user, f"{provider}.access_token", new_token)
    _store(db, user, f"{provider}.expires_at", str(int(time.time()) + int(data.get("expires_in", 3600)) - 60))
    return new_token


async def api_get(db: Session, user: User, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    token = await access_token(db, user, "youtube" if "youtube" in url else "google")
    if not token:
        raise PermissionError("Google account not connected")
    async with httpx.AsyncClient(timeout=40) as client:
        res = await client.get(url, params=params or {}, headers={"Authorization": f"Bearer {token}"})
        if res.status_code >= 400:
            raise RuntimeError(f"Google API {res.status_code}: {res.text[:300]}")
        return res.json()


async def api_post(db: Session, user: User, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    token = await access_token(db, user, "google")
    if not token:
        raise PermissionError("Google account not connected")
    async with httpx.AsyncClient(timeout=40) as client:
        res = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
        if res.status_code >= 400:
            raise RuntimeError(f"Google API {res.status_code}: {res.text[:300]}")
        return res.json()


# ------------------------------------------------------------------ Gmail
async def gmail_messages(db: Session, user: User, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    listing = await api_get(
        db, user, "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        {"q": query, "maxResults": min(int(limit), 25)},
    )
    messages: List[Dict[str, Any]] = []
    for item in listing.get("messages", [])[:limit]:
        detail = await api_get(
            db, user, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}",
            {"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
        )
        headers = {h["name"].lower(): h["value"] for h in detail.get("payload", {}).get("headers", [])}
        messages.append(
            {
                "id": item["id"],
                "thread_id": detail.get("threadId", ""),
                "subject": headers.get("subject", "(no subject)"),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "snippet": detail.get("snippet", ""),
                "labels": detail.get("labelIds", []),
            }
        )
    return messages


async def gmail_send(db: Session, user: User, to: str, subject: str, body: str, thread_id: str = "") -> Dict[str, Any]:
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    payload: Dict[str, Any] = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    return await api_post(db, user, "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", payload)


# ------------------------------------------------------------------ Calendar
async def calendar_events(db: Session, user: User, days: int = 7) -> List[Dict[str, Any]]:
    from datetime import datetime, timedelta, timezone

    time_min = datetime.now(timezone.utc).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=max(1, int(days)))).isoformat()
    data = await api_get(
        db, user, "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "orderBy": "startTime", "maxResults": 50},
    )
    events = []
    for item in data.get("items", []):
        events.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary", "(untitled)"),
                "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date"),
                "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
                "location": item.get("location", ""),
                "attendees": [a.get("email") for a in item.get("attendees", []) if a.get("email")],
                "html_link": item.get("htmlLink", ""),
            }
        )
    return events


async def calendar_create(
    db: Session, user: User, summary: str, start: str, end: str, description: str = "", attendees: Optional[List[str]] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if attendees:
        payload["attendees"] = [{"email": email} for email in attendees]
    return await api_post(db, user, "https://www.googleapis.com/calendar/v3/calendars/primary/events", payload)


async def profile(db: Session, user: User) -> Dict[str, Any]:
    token = await access_token(db, user, "google")
    if not token:
        raise PermissionError("Google account not connected")
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {token}"})
        res.raise_for_status()
        return res.json()
