"""Desktop bridge endpoints.

The bridge authenticates with a shared token, long-polls for one allowlisted job
at a time, and reports output. No shell is exposed over the user API.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import DesktopJob, User, utcnow
from ..security import get_current_user, verify_desktop_token
from ..serializers import desktop_job_dict

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


def _bridge(x_bridge_token: str = Header(default="")) -> None:
    if not verify_desktop_token(x_bridge_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bridge token")


class ReportBody(BaseModel):
    job_id: str
    output: str = ""
    exit_code: Optional[int] = None


@router.get("/jobs")
def jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(DesktopJob).filter(DesktopJob.user_id == user.id)
        .order_by(desc(DesktopJob.created_at)).limit(50).all()
    )
    return {
        "jobs": [desktop_job_dict(j) for j in rows],
        "allowlist": settings.desktop_allowlist,
        "bridge_configured": bool(settings.desktop_bridge_token),
    }


@router.get("/poll")
def poll(db: Session = Depends(get_db), _: None = Depends(_bridge)) -> dict:
    job = (
        db.query(DesktopJob).filter(DesktopJob.status == "queued")
        .order_by(DesktopJob.created_at).first()
    )
    if job is None:
        return {"job": None}
    job.status = "running"
    db.commit()
    return {"job": {"id": job.id, "command": job.command, "cwd": job.cwd}}


@router.post("/report")
def report(body: ReportBody, db: Session = Depends(get_db), _: None = Depends(_bridge)) -> dict:
    job = db.get(DesktopJob, body.job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    job.output = body.output[-20000:]
    job.exit_code = body.exit_code
    job.status = "done" if (body.exit_code or 0) == 0 else "failed"
    job.finished_at = utcnow()
    db.commit()
    return {"ok": True}
