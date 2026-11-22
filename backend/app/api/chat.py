"""Conversational entry point (web + PWA). Also handles browser-recorded voice."""
from __future__ import annotations

import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..agent.orchestrator import acknowledgement, record_chat, submit_task
from ..db import get_db
from ..models import ChatMessage, Task, User
from ..security import get_current_user, rate_limiter
from ..serializers import chat_dict, task_dict
from ..services.whatsapp import transcribe_audio

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MessageBody(BaseModel):
    content: str
    source: str = "web"


@router.get("/messages")
def messages(
    limit: int = 80, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user.id, ChatMessage.source != "whatsapp")
        .order_by(desc(ChatMessage.created_at))
        .limit(min(limit, 300))
        .all()
    )
    return {"messages": [chat_dict(m) for m in reversed(rows)]}


@router.post("/messages")
async def send_message(
    body: MessageBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    content = body.content.strip()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message is empty")
    rate_limiter.check(f"chat:{user.id}", 40, 60)
    record_chat(db, user, "user", content, source="web")
    try:
        task = await submit_task(db, user, content, source="web")
    except ValueError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    reply = acknowledgement(task)
    assistant = record_chat(db, user, "assistant", reply, task_id=task.id, source="web")
    return {"reply": chat_dict(assistant), "task": task_dict(task)}


@router.post("/voice")
async def voice_message(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rate_limiter.check(f"voice:{user.id}", 20, 60)
    payload = await file.read()
    if len(payload) > 12 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Voice file too large (max 12 MB)")
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as tmp:
        tmp.write(payload)
        tmp.flush()
        with open(tmp.name, "rb") as handle:
            transcript = await transcribe_audio(handle.read(), file.content_type or "audio/webm")
    if not transcript:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Voice transcription needs OPENAI_API_KEY or GEMINI_API_KEY. Text commands work without it.",
        )
    record_chat(db, user, "user", f"🎙 {transcript}", source="web")
    task = await submit_task(db, user, transcript, source="voice")
    reply = acknowledgement(task)
    assistant = record_chat(db, user, "assistant", reply, task_id=task.id, source="web")
    return {"transcript": transcript, "reply": chat_dict(assistant), "task": task_dict(task)}


@router.get("/context")
def context(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    active = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.status.in_(["queued", "running", "planning", "waiting_approval"]))
        .order_by(desc(Task.created_at))
        .limit(5)
        .all()
    )
    return {"active_tasks": [task_dict(t) for t in active]}
