"""Read-only analytics endpoints for the YouTube and Instagram studios."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import get_current_user
from ..services import google_api
from ..tools.base import ToolContext
from ..tools.instagram import instagram_analytics
from ..tools.youtube import youtube_analytics

router = APIRouter(prefix="/api/publishing", tags=["publishing"])


def _ctx(db: Session, user: User) -> ToolContext:
    return ToolContext(db=db, user=user, task=None, emit=lambda *args, **kwargs: None)


@router.get("/youtube/analytics")
async def yt_analytics(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    ctx = _ctx(db, user)
    result = await youtube_analytics(ctx)
    return {
        "ok": result.ok,
        "configured": google_api.configured(),
        "detail": result.summary,
        "data": result.data,
        "setup_required": result.setup_required,
    }


@router.get("/instagram/analytics")
async def ig_analytics(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    ctx = _ctx(db, user)
    result = await instagram_analytics(ctx)
    return {
        "ok": result.ok,
        "detail": result.summary,
        "data": result.data,
        "setup_required": result.setup_required,
        "requires_public_url": True,
    }
