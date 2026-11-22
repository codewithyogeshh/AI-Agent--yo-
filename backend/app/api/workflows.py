"""Content automation workflows (daily / interval schedules)."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..agent.worker import _next_run
from ..db import get_db
from ..models import User, Workflow, utcnow
from ..security import audit, get_current_user
from ..serializers import workflow_dict

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowBody(BaseModel):
    name: str
    prompt: str
    kind: str = "content"
    schedule_kind: str = "daily"
    at_time: str = "09:00"
    interval_minutes: int = 1440
    publishing_mode: str = "approval"
    enabled: bool = True


@router.get("")
def list_workflows(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.query(Workflow).filter(Workflow.user_id == user.id).order_by(desc(Workflow.created_at)).all()
    return {"workflows": [workflow_dict(w) for w in rows]}


@router.post("")
def create_workflow(body: WorkflowBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if body.publishing_mode not in {"draft", "approval", "auto"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "publishing_mode must be draft, approval or auto")
    workflow = Workflow(
        user_id=user.id,
        name=body.name[:200],
        prompt=body.prompt,
        kind=body.kind,
        schedule_kind=body.schedule_kind if body.schedule_kind in {"daily", "interval"} else "daily",
        at_time=body.at_time,
        interval_minutes=max(5, body.interval_minutes),
        publishing_mode=body.publishing_mode,
        enabled=body.enabled,
    )
    workflow.next_run_at = _next_run(workflow, utcnow())
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    audit(db, user.id, "workflow.create", workflow.id, data={"name": workflow.name})
    return {"workflow": workflow_dict(workflow)}


@router.patch("/{workflow_id}")
def update_workflow(
    workflow_id: str, body: dict,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or workflow.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    for field in ("name", "prompt", "kind", "at_time", "publishing_mode"):
        if field in body:
            setattr(workflow, field, body[field])
    if "interval_minutes" in body:
        workflow.interval_minutes = max(5, int(body["interval_minutes"]))
    if "enabled" in body:
        workflow.enabled = bool(body["enabled"])
    workflow.next_run_at = _next_run(workflow, utcnow()) if workflow.enabled else None
    db.commit()
    return {"workflow": workflow_dict(workflow)}


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or workflow.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    db.delete(workflow)
    db.commit()
    return {"ok": True}
