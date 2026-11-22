"""Event triggers — signed inbound webhooks that create tasks.

The fire endpoint is public by design (an external service cannot hold a NOVA
session), so it is authenticated by a per-trigger HMAC over the raw body, gated
by filters, deduplicated by delivery id and rate limited. Everything after that
goes through the normal orchestrator: planning, permissions, approvals, audit.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..agent.orchestrator import submit_task
from ..config import settings
from ..db import get_db
from ..models import Trigger, TriggerDelivery, User, utcnow
from ..security import audit, get_current_user
from ..services import triggers as trigger_service

router = APIRouter(prefix="/api/triggers", tags=["triggers"])

SUPPORTED_KINDS = {"webhook"}


def _dict(trigger: Trigger, base: str = "") -> Dict[str, Any]:
    path = f"/api/triggers/{trigger.id}/fire"
    public = f"{base.rstrip('/')}{path}" if base else ""
    return {
        "id": trigger.id,
        "name": trigger.name,
        "kind": trigger.kind,
        "prompt_template": trigger.prompt_template,
        "filters": trigger_service.parse_filters(trigger.filters_json),
        "enabled": trigger.enabled,
        "fire_count": trigger.fire_count,
        "last_fired_at": trigger.last_fired_at.isoformat() if trigger.last_fired_at else None,
        "last_error": trigger.last_error,
        "created_at": trigger.created_at.isoformat() if trigger.created_at else None,
        "endpoint": path,
        "public_endpoint": public,
    }


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt_template: str = Field(min_length=3, max_length=8000)
    filters: Dict[str, Any] = Field(default_factory=dict)
    kind: str = "webhook"


class UpdateBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    prompt_template: Optional[str] = Field(default=None, min_length=3, max_length=8000)
    filters: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


def _owned(db: Session, user: User, trigger_id: str) -> Trigger:
    trigger = db.get(Trigger, trigger_id)
    if trigger is None or trigger.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trigger not found")
    return trigger


@router.get("")
def list_triggers(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(Trigger)
        .filter(Trigger.user_id == user.id)
        .order_by(desc(Trigger.created_at))
        .limit(100)
        .all()
    )
    return {"triggers": [_dict(row) for row in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_trigger(
    body: CreateBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if body.kind not in SUPPORTED_KINDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Kind “{body.kind}” is not available yet. Webhook triggers are supported today; "
            "Gmail watch and calendar pollers reuse the same table and land next.",
        )
    secret = trigger_service.new_secret()
    trigger = Trigger(
        user_id=user.id,
        name=body.name.strip(),
        kind=body.kind,
        prompt_template=body.prompt_template.strip(),
        filters_json=json.dumps(body.filters, default=str),
        secret_enc=trigger_service.seal(secret),
    )
    db.add(trigger)
    db.commit()
    db.refresh(trigger)
    audit(db, user.id, "trigger.created", trigger.id, data={"kind": trigger.kind, "name": trigger.name})
    data = _dict(trigger, settings.public_base_url)
    data["secret"] = secret  # shown exactly once
    data["note"] = (
        "Sign the raw request body with HMAC-SHA256 using this secret and send it as "
        "X-NOVA-Signature: sha256=<hex>. Send X-NOVA-Delivery to deduplicate retries."
    )
    return {"trigger": data}


@router.patch("/{trigger_id}")
def update_trigger(
    trigger_id: str,
    body: UpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    trigger = _owned(db, user, trigger_id)
    if body.name is not None:
        trigger.name = body.name.strip()
    if body.prompt_template is not None:
        trigger.prompt_template = body.prompt_template.strip()
    if body.filters is not None:
        trigger.filters_json = json.dumps(body.filters, default=str)
    if body.enabled is not None:
        trigger.enabled = body.enabled
    db.commit()
    db.refresh(trigger)
    audit(db, user.id, "trigger.updated", trigger.id, data={"enabled": trigger.enabled})
    return {"trigger": _dict(trigger, settings.public_base_url)}


@router.delete("/{trigger_id}")
def delete_trigger(
    trigger_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    trigger = _owned(db, user, trigger_id)
    db.query(TriggerDelivery).filter(TriggerDelivery.trigger_id == trigger.id).delete()
    db.delete(trigger)
    db.commit()
    audit(db, user.id, "trigger.deleted", trigger_id)
    return {"deleted": trigger_id}


@router.post("/{trigger_id}/rotate-secret")
def rotate_secret(
    trigger_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    trigger = _owned(db, user, trigger_id)
    secret = trigger_service.new_secret()
    trigger.secret_enc = trigger_service.seal(secret)
    db.commit()
    audit(db, user.id, "trigger.secret_rotated", trigger.id)
    return {"trigger": trigger.id, "secret": secret}


@router.post("/{trigger_id}/fire", status_code=status.HTTP_202_ACCEPTED)
async def fire(trigger_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Public, signature-authenticated entry point for external events."""
    raw = await request.body()
    if len(raw) > trigger_service.MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large (64 KB max)")

    trigger = db.get(Trigger, trigger_id)
    if trigger is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown trigger")
    if not trigger.enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Trigger is disabled")
    try:
        secret = trigger_service.unseal(trigger.secret_enc)
    except Exception:  # noqa: BLE001 - unreadable secret must not 500 blindly
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Trigger secret is unreadable; rotate it")
    if not trigger_service.signature_valid(secret, raw, request.headers.get("x-nova-signature", "")):
        audit(
            db, trigger.user_id, "trigger.rejected", trigger.id,
            level="warning", actor="webhook", data={"reason": "invalid_signature"},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    if trigger_service.rate_limited(trigger.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many events for this trigger")

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body must be JSON") from exc
    if not isinstance(payload, dict):
        payload = {"value": payload}

    delivery_id = (request.headers.get("x-nova-delivery") or "").strip()[:200]
    if delivery_id:
        seen = (
            db.query(TriggerDelivery)
            .filter(TriggerDelivery.trigger_id == trigger.id, TriggerDelivery.delivery_id == delivery_id)
            .first()
        )
        if seen is not None:
            return {"trigger": trigger.id, "duplicate": True, "task_id": None}

    if not trigger_service.matches(trigger_service.parse_filters(trigger.filters_json), payload):
        return {"trigger": trigger.id, "skipped": "filters", "task_id": None}

    user = db.get(User, trigger.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Trigger owner is not active")

    prompt = trigger_service.render_prompt(trigger.prompt_template, payload)
    try:
        task = await submit_task(db, user, prompt, source="trigger")
    except ValueError as exc:
        trigger.last_error = str(exc)[:1000]
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    if delivery_id:
        db.add(TriggerDelivery(trigger_id=trigger.id, delivery_id=delivery_id))
    trigger.fire_count += 1
    trigger.last_fired_at = utcnow()
    trigger.last_error = ""
    db.commit()
    audit(
        db, user.id, "trigger.fired", trigger.id,
        actor="webhook",
        ip=request.client.host if request.client else "",
        data={
            "task_id": task.id,
            "delivery": delivery_id,
            "kind": trigger.kind,
            "payload_keys": sorted(payload.keys())[:20],
        },
    )
    return {
        "trigger": trigger.id,
        "task_id": task.id,
        "status": task.status,
        "task_url": f"/api/tasks/{task.id}",
    }
