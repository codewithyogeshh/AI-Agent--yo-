"""System health, overview metrics, settings, logs, notifications and event streams."""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from ..agent import llm, permissions
from ..agent.worker import worker
from ..config import settings
from ..db import get_db
from ..models import Approval, AuditLog, ContentItem, Notification, Task, User, utcnow
from ..realtime import active_subscribers, bus
from ..security import audit, decode_token, get_current_user, rate_limiter
from ..serializers import log_dict, notification_dict, task_dict
from ..services import media
from ..services.integration_registry import integration_status
from ..tools import list_tools

router = APIRouter(prefix="/api/system", tags=["system"])


def _user_from_token_param(t: str, db: Session) -> Optional[User]:
    try:
        payload = decode_token(t)
    except jwt.PyJWTError:
        return None
    return db.get(User, payload.get("sub"))


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "nova-backend", "time": utcnow().isoformat(), "env": settings.env}


@router.get("/asset-token")
def asset_token(user: User = Depends(get_current_user)) -> dict:
    now = int(time.time())
    token = jwt.encode(
        {"sub": user.id, "scope": "asset", "iss": "nova", "iat": now, "exp": now + 6 * 3600},
        settings.secret_key,
        algorithm="HS256",
    )
    return {"token": token, "expires_in": 6 * 3600}


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    counts = dict(
        db.query(Task.status, func.count(Task.id)).filter(Task.user_id == user.id).group_by(Task.status).all()
    )
    since = utcnow() - timedelta(days=7)
    daily = []
    for offset in range(6, -1, -1):
        day = (utcnow() - timedelta(days=offset)).date()
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=offset)
        end = start + timedelta(days=1)
        total = db.query(Task).filter(Task.user_id == user.id, Task.created_at >= start, Task.created_at < end).count()
        done = db.query(Task).filter(
            Task.user_id == user.id, Task.status == "completed", Task.created_at >= start, Task.created_at < end
        ).count()
        daily.append({"date": day.isoformat(), "created": total, "completed": done})

    recent = db.query(Task).filter(Task.user_id == user.id).order_by(desc(Task.created_at)).limit(8).all()
    upcoming = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.scheduled_for.isnot(None), Task.scheduled_for >= utcnow())
        .order_by(Task.scheduled_for)
        .limit(6)
        .all()
    )
    latest_content = (
        db.query(ContentItem).filter(ContentItem.user_id == user.id).order_by(desc(ContentItem.created_at)).limit(4).all()
    )
    from ..serializers import content_dict

    stats = {
        "total": sum(counts.values()),
        "active": sum(counts.get(key, 0) for key in ("queued", "running", "planning")),
        "completed_week": db.query(Task).filter(
            Task.user_id == user.id, Task.status == "completed", Task.finished_at >= since
        ).count(),
        "failed_week": db.query(Task).filter(
            Task.user_id == user.id, Task.status == "failed", Task.finished_at >= since
        ).count(),
        "pending_approvals": db.query(Approval).filter(
            Approval.user_id == user.id, Approval.status == "pending"
        ).count(),
        "unread_notifications": db.query(Notification).filter(
            Notification.user_id == user.id, Notification.read.is_(False)
        ).count(),
        "content_drafts": db.query(ContentItem).filter(
            ContentItem.user_id == user.id, ContentItem.status.in_(["draft", "rendered", "scheduled"])
        ).count(),
    }
    usage = shutil.disk_usage(settings.workspace_dir)
    return {
        "stats": stats,
        "status_counts": counts,
        "daily": daily,
        "recent_tasks": [task_dict(t) for t in recent],
        "upcoming": [task_dict(t) for t in upcoming],
        "latest_content": [content_dict(c) for c in latest_content],
        "system": {
            "worker": worker.status(),
            "queue_depth": db.query(Task).filter(Task.status == "queued").count(),
            "ai": llm.capabilities(),
            "media": media.capabilities(),
            "realtime_subscribers": active_subscribers(),
            "storage": {
                "workspace_bytes": usage.used,
                "free_bytes": usage.free,
                "database_url_kind": settings.database_url.split(":")[0],
            },
            "integrations": [
                {"id": i["id"], "name": i["name"], "status": i["status"]}
                for i in integration_status(db, user)
            ],
        },
    }


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {"settings": permissions.get_settings_map(db, user)}


@router.put("/settings")
def update_settings(
    payload: Dict[str, Any], user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    allowed = set(permissions.DEFAULT_SETTINGS.keys())
    for key, value in payload.items():
        if key in allowed:
            permissions.put_setting(db, user, key, value)
    audit(db, user.id, "settings.update", data={k: v for k, v in payload.items() if k in allowed})
    return {"settings": permissions.get_settings_map(db, user)}


@router.get("/tools")
def tools(user: User = Depends(get_current_user)) -> dict:
    return {
        "tools": [
            {**t.spec(), "headline": t.description}
            for t in list_tools()
        ]
    }


@router.get("/logs")
def logs(
    limit: int = 100, level: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    query = db.query(AuditLog)
    if level:
        query = query.filter(AuditLog.level == level)
    rows = query.order_by(desc(AuditLog.created_at)).limit(min(limit, 500)).all()
    return {"logs": [log_dict(r) for r in rows]}


@router.get("/notifications")
def notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(Notification).filter(Notification.user_id == user.id)
        .order_by(desc(Notification.created_at)).limit(100).all()
    )
    return {"notifications": [notification_dict(r) for r in rows]}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    row.read = True
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read.is_(False)).update({"read": True})
    db.commit()
    return {"ok": True}


@router.get("/events")
async def events(t: str = Query(""), db: Session = Depends(get_db)):
    user = _user_from_token_param(t, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Valid token required")
    queue = bus.subscribe()

    async def generator():
        try:
            yield 'event: ready\ndata: {"ok":true}\n\n'
            async for event in bus.stream(queue):
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/capabilities")
def capabilities(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {
        "ai": llm.capabilities(),
        "media": media.capabilities(),
        "integrations": integration_status(db, user),
        "worker": worker.status(),
    }
