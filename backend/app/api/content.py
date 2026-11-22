"""Content library, video assets, drafts and publishing requests."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ContentItem, MediaAsset, Task, User
from ..security import audit, decode_token, get_current_user
from ..serializers import asset_dict, content_dict, task_dict
from ..services import whatsapp

router = APIRouter(prefix="/api/content", tags=["content"])


class GenerateBody(BaseModel):
    topic: str
    platform: str = "youtube"
    format: str = "vertical"
    duration: int = 60


class DraftBody(BaseModel):
    platform: str = "youtube"
    title: str
    caption: str = ""
    script: str = ""
    hashtags: str = ""
    kind: str = "short"


class PatchBody(BaseModel):
    title: Optional[str] = None
    caption: Optional[str] = None
    script: Optional[str] = None
    hashtags: Optional[str] = None
    status: Optional[str] = None
    scheduled_for: Optional[datetime] = None


class PublishBody(BaseModel):
    privacy: str = "private"
    publish_at: str = ""


def _asset_user(t: str) -> Optional[str]:
    try:
        payload = decode_token(t)
    except jwt.PyJWTError:
        return None
    if payload.get("scope") not in {"asset", None}:
        return None
    return payload.get("sub")


@router.get("")
def list_content(
    platform: str = "", status_filter: str = Query("", alias="status"),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    query = db.query(ContentItem).filter(ContentItem.user_id == user.id)
    if platform:
        query = query.filter(ContentItem.platform == platform)
    if status_filter:
        query = query.filter(ContentItem.status == status_filter)
    rows = query.order_by(desc(ContentItem.created_at)).limit(200).all()
    return {"items": [content_dict(i) for i in rows], "count": len(rows)}


@router.get("/library")
def library(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    items = db.query(ContentItem).filter(ContentItem.user_id == user.id).order_by(desc(ContentItem.created_at)).limit(100).all()
    assets = db.query(MediaAsset).filter(MediaAsset.user_id == user.id).order_by(desc(MediaAsset.created_at)).limit(200).all()
    return {"items": [content_dict(i) for i in items], "assets": [asset_dict(a) for a in assets]}


@router.post("/generate")
async def generate(
    body: GenerateBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    from ..agent.orchestrator import submit_task

    platform = body.platform if body.platform in {"youtube", "instagram"} else "youtube"
    prompt = (
        f"Create a {body.duration}-second {body.format} {platform} video about: {body.topic}. "
        "Write the script, produce the video with subtitles, make a thumbnail and save a draft."
    )
    task = await submit_task(db, user, prompt, source="studio")
    task.approval_required = platform in {"youtube", "instagram"}
    db.commit()
    audit(db, user.id, "content.generate", task.id, data={"platform": platform, "topic": body.topic[:100]})
    return {"task": task_dict(task), "message": "Production queued. I will update you as each stage completes."}


@router.post("")
def create_draft(body: DraftBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = ContentItem(
        user_id=user.id, platform=body.platform, title=body.title[:250], caption=body.caption,
        script=body.script, hashtags=body.hashtags, kind=body.kind, status="draft",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"item": content_dict(item)}


@router.patch("/{content_id}")
def patch_content(
    content_id: str, body: PatchBody,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    item = db.get(ContentItem, content_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Content not found")
    for field in ("title", "caption", "script", "hashtags", "status"):
        value = getattr(body, field)
        if value is not None:
            setattr(item, field, value)
    if body.scheduled_for is not None:
        item.scheduled_for = body.scheduled_for
    item.updated_at = datetime.utcnow()
    db.commit()
    return {"item": content_dict(item)}


@router.delete("/{content_id}")
def delete_content(content_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(ContentItem, content_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Content not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/{content_id}/publish")
async def publish(
    content_id: str, body: PublishBody,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    item = db.get(ContentItem, content_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Content not found")
    if item.platform == "youtube":
        if not item.asset_path:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No rendered video to upload yet")
        plan = [{
            "tool": "youtube.upload",
            "args": {"content_id": item.id, "privacy": body.privacy, "publish_at": body.publish_at},
            "label": f"Upload “{item.title[:50]}” to YouTube ({body.privacy})",
            "status": "pending", "index": 0,
        }]
    elif item.platform == "instagram":
        plan = [{
            "tool": "instagram.publish",
            "args": {"content_id": item.id},
            "label": "Publish the reel to Instagram",
            "status": "pending", "index": 0,
        }]
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown platform {item.platform}")

    task = Task(
        user_id=user.id, title=f"Publish: {item.title[:200]}", prompt=f"Publish content {item.id}",
        kind="publish", agent=item.platform, status="queued", plan_json=json.dumps(plan),
        source="studio", approval_required=True,
    )
    db.add(task)
    db.commit()
    audit(db, user.id, "content.publish_requested", item.id, data={"task": task.id})
    return {"task": task_dict(task), "message": "Queued. Publishing always waits for your approval."}


@router.get("/{content_id}/asset")
def get_asset(
    content_id: str, t: str = Query(""), db: Session = Depends(get_db)
) -> FileResponse:
    user_id = _asset_user(t)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Valid asset token required")
    item = db.get(ContentItem, content_id)
    if item is None or item.user_id != user_id or not item.asset_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
    path = Path(item.asset_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on disk")
    return FileResponse(path, media_type="video/mp4", filename=f"{content_id}.mp4")


@router.get("/{content_id}/thumbnail")
def get_thumbnail(content_id: str, t: str = Query(""), db: Session = Depends(get_db)):
    user_id = _asset_user(t)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Valid asset token required")
    item = db.get(ContentItem, content_id)
    if item is None or item.user_id != user_id or not item.thumb_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thumbnail not found")
    path = Path(item.thumb_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on disk")
    return FileResponse(path, media_type="image/png")
