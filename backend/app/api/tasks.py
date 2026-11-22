"""Task API: create from natural language, inspect, control, retry."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from ..agent.orchestrator import acknowledgement, submit_task
from ..db import get_db
from ..models import Approval, Task, TaskEvent, User, utcnow
from ..security import audit, get_current_user, rate_limiter
from ..serializers import approval_dict, event_dict, task_dict

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

ACTIVE = {"pending", "planning", "queued", "running"}


class CreateTaskBody(BaseModel):
    prompt: str
    title: str = ""
    priority: int = 2
    scheduled_for: Optional[datetime] = None
    recurrence: str = ""


class UpdateTaskBody(BaseModel):
    title: Optional[str] = None
    priority: Optional[int] = None
    status: Optional[str] = None
    scheduled_for: Optional[datetime] = None


@router.get("")
def list_tasks(
    status_filter: str = Query("", alias="status"),
    q: str = "",
    kind: str = "",
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Task).filter(Task.user_id == user.id)
    if status_filter and status_filter != "all":
        query = query.filter(Task.status == status_filter)
    if kind:
        query = query.filter(Task.kind == kind)
    if q:
        query = query.filter(or_(Task.title.ilike(f"%{q}%"), Task.prompt.ilike(f"%{q}%")))
    rows = query.order_by(desc(Task.created_at)).limit(min(limit, 300)).all()
    return {"tasks": [task_dict(t) for t in rows], "count": len(rows)}


@router.post("")
async def create_task(
    body: CreateTaskBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rate_limiter.check(f"task:{user.id}", 30, 60)
    try:
        task = await submit_task(db, user, body.prompt, source="web")
    except ValueError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    if body.title:
        task.title = body.title[:290]
    if body.priority:
        task.priority = max(1, min(3, body.priority))
    if body.scheduled_for:
        task.scheduled_for = body.scheduled_for
        task.status = "scheduled"
    if body.recurrence in {"daily", "weekly"}:
        task.recurrence = body.recurrence
    db.commit()
    audit(db, user.id, "task.create", task.id, data={"kind": task.kind, "source": "web"})
    return {"task": task_dict(task, detail=True, events=task.events), "acknowledgement": acknowledgement(task)}


@router.get("/{task_id}")
def get_task(
    task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    events = (
        db.query(TaskEvent).filter(TaskEvent.task_id == task.id).order_by(TaskEvent.seq.asc()).all()
    )
    pending = db.query(Approval).filter(Approval.task_id == task.id, Approval.status == "pending").all()
    return {
        "task": task_dict(task, detail=True, events=events),
        "events": [event_dict(e) for e in events],
        "approvals": [approval_dict(a) for a in pending],
    }


@router.patch("/{task_id}")
def update_task(
    task_id: str, body: UpdateTaskBody,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if body.title is not None:
        task.title = body.title[:290]
    if body.priority is not None:
        task.priority = max(1, min(3, body.priority))
    if body.scheduled_for is not None:
        task.scheduled_for = body.scheduled_for
        if task.status in {"pending", "scheduled"}:
            task.status = "scheduled"
    if body.status:
        _apply_status(db, task, body.status)
    db.commit()
    return {"task": task_dict(task, detail=True)}


def _apply_status(db: Session, task: Task, new_status: str) -> None:
    allowed = {"pending", "planning", "queued", "running", "waiting_approval", "paused", "completed", "failed", "cancelled"}
    if new_status not in allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown status {new_status}")
    if new_status in {"cancelled", "completed", "failed"} and task.status == "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Completed tasks cannot be reopened")
    task.status = new_status
    if new_status in {"cancelled", "failed"}:
        task.finished_at = utcnow()
    if new_status == "queued":
        db.add(TaskEvent(task_id=task.id, seq=999_999, type="status", message="Re-queued by user"))


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if task.status in {"completed", "failed", "cancelled"}:
        return {"task": task_dict(task, detail=True), "changed": False}
    task.status = "cancelled"
    task.finished_at = utcnow()
    task.error = task.error or "Cancelled by user"
    db.add(TaskEvent(task_id=task.id, seq=999_998, type="status", message="Cancelled by user"))
    db.commit()
    audit(db, user.id, "task.cancel", task.id)
    return {"task": task_dict(task, detail=True), "changed": True}


@router.post("/{task_id}/pause")
def pause_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Finished tasks cannot be paused")
    task.status = "paused"
    db.add(TaskEvent(task_id=task.id, seq=999_997, type="status", message="Paused by user"))
    db.commit()
    return {"task": task_dict(task, detail=True)}


@router.post("/{task_id}/resume")
def resume_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if task.status == "paused":
        task.status = "queued"
        db.add(TaskEvent(task_id=task.id, seq=999_996, type="status", message="Resumed by user"))
        db.commit()
    return {"task": task_dict(task, detail=True)}


@router.post("/{task_id}/retry")
def retry_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if task.status not in {"failed", "cancelled"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed or cancelled tasks can be retried")
    import json

    plan = json.loads(task.plan_json or "[]")
    for step in plan:
        step["status"] = "pending"
        step.pop("error", None)
        step["approved"] = False
    task.plan_json = json.dumps(plan)
    task.status = "queued"
    task.error = ""
    task.progress = 0
    task.finished_at = None
    db.add(TaskEvent(task_id=task.id, seq=999_995, type="status", message="Retry requested by user"))
    db.commit()
    return {"task": task_dict(task, detail=True)}


@router.delete("/{task_id}")
def delete_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if task.status in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cancel the task before deleting it")
    db.delete(task)
    db.commit()
    audit(db, user.id, "task.delete", task_id)
    return {"ok": True}
