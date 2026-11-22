"""Direct user-initiated Gmail / Calendar endpoints for the dashboard pages.

These are explicit user actions from the UI (not autonomous agent actions), so
they execute immediately but are always audit-logged. If Google is not connected
the response says so instead of returning placeholder data.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..security import audit, get_current_user
from ..services import google_api

router = APIRouter(prefix="/api/productivity", tags=["productivity"])


class SendEmailBody(BaseModel):
    to: str
    subject: str
    body: str


class CreateEventBody(BaseModel):
    summary: str
    start: str
    end: str
    description: str = ""


def _connected(db: Session, user: User) -> bool:
    if not google_api.configured():
        return False
    return google_api._read(db, user, "google.refresh_token") != "" or google_api._read(db, user, "google.access_token") != ""


@router.get("/status")
def productivity_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {
        "google_configured": google_api.configured(),
        "connected": _connected(db, user),
        "redirect_uri": settings.google_redirect_uri,
    }


@router.get("/emails")
async def emails(
    query: str = "is:unread", limit: int = 15,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    if not _connected(db, user):
        return {"connected": False, "emails": [], "query": query}
    try:
        messages = await google_api.gmail_messages(db, user, query, min(limit, 25))
    except PermissionError:
        return {"connected": False, "emails": [], "query": query}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gmail error: {exc}") from exc
    return {"connected": True, "emails": messages, "query": query}


@router.post("/emails/send")
async def send_email(
    body: SendEmailBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not _connected(db, user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gmail is not connected")
    if not body.to or not body.subject:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Recipient and subject are required")
    try:
        result = await google_api.gmail_send(db, user, body.to, body.subject, body.body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Send failed: {exc}") from exc
    audit(db, user.id, "email.send_manual", body.to, data={"subject": body.subject[:120]})
    return {"ok": True, "message_id": result.get("id", "")}


@router.get("/events")
async def events(
    days: int = 7, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not _connected(db, user):
        return {"connected": False, "events": []}
    try:
        rows = await google_api.calendar_events(db, user, days)
    except PermissionError:
        return {"connected": False, "events": []}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Calendar error: {exc}") from exc
    return {"connected": True, "events": rows}


@router.post("/events")
async def create_event(
    body: CreateEventBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not _connected(db, user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google Calendar is not connected")
    try:
        event = await google_api.calendar_create(db, user, body.summary, body.start, body.end, body.description)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Calendar write failed: {exc}") from exc
    audit(db, user.id, "calendar.create_manual", event.get("id", ""), data={"summary": body.summary[:120]})
    return {"ok": True, "event_id": event.get("id", ""), "html_link": event.get("htmlLink", "")}
