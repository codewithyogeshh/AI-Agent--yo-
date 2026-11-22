"""Approval workflow: review, approve, reject. Approving re-queues the task.

All decision logic lives in `services.approvals` so the WhatsApp channel applies
exactly the same transitions and audit records as this API.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Approval, Task, User
from ..security import get_current_user
from ..serializers import approval_dict, task_dict
from ..services import approvals as approval_service

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class DecisionBody(BaseModel):
    approve: bool
    note: str = ""


@router.get("")
def list_approvals(
    status_filter: str = "pending", user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    query = db.query(Approval).filter(Approval.user_id == user.id)
    if status_filter != "all":
        query = query.filter(Approval.status == status_filter)
    rows = query.order_by(desc(Approval.created_at)).limit(100).all()
    titles = {
        t.id: t.title
        for t in db.query(Task).filter(Task.id.in_([r.task_id for r in rows if r.task_id])).all()
    }
    return {"approvals": [approval_dict(a, titles.get(a.task_id, "")) for a in rows]}


@router.post("/{approval_id}/decide")
async def decide(
    approval_id: str,
    body: DecisionBody,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    approval = db.get(Approval, approval_id)
    if approval is None or approval.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    try:
        approval, task = approval_service.decide(
            db,
            user,
            approval,
            body.approve,
            body.note,
            actor="dashboard",
            ip=request.client.host if request.client else "",
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"approval": approval_dict(approval), "task": task_dict(task, detail=True) if task else None}
