"""Memory CRUD, search and export. Secrets are refused before they reach storage."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Memory, User
from ..security import audit, get_current_user
from ..serializers import memory_dict
from ..tools.memory import _looks_sensitive

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryBody(BaseModel):
    title: str
    content: str
    kind: str = "fact"
    tags: list[str] = []
    importance: int = 2


class MemoryPatch(BaseModel):
    title: str | None = None
    content: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    importance: int | None = None


@router.get("")
def list_memory(
    q: str = "", kind: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    query = db.query(Memory).filter(Memory.user_id == user.id)
    if kind:
        query = query.filter(Memory.kind == kind)
    if q:
        query = query.filter(
            or_(Memory.title.ilike(f"%{q}%"), Memory.content.ilike(f"%{q}%"), Memory.tags.ilike(f"%{q}%"))
        )
    rows = query.order_by(desc(Memory.importance), desc(Memory.updated_at)).limit(300).all()
    return {"memories": [memory_dict(m) for m in rows]}


@router.post("")
def create_memory(body: MemoryBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if _looks_sensitive(body.content) or _looks_sensitive(body.title):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That looks like a credential or financial detail. NOVA does not store secrets in memory.",
        )
    memory = Memory(
        user_id=user.id,
        title=body.title[:200],
        content=body.content,
        kind=body.kind,
        tags=",".join(body.tags),
        importance=max(1, min(3, body.importance)),
        source="user",
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return {"memory": memory_dict(memory)}


@router.patch("/{memory_id}")
def update_memory(
    memory_id: str, body: MemoryPatch,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    memory = db.get(Memory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found")
    if body.content is not None and _looks_sensitive(body.content):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Refusing to store credentials")
    if body.content is not None:
        memory.content = body.content
    if body.title is not None:
        memory.title = body.title[:200]
    if body.kind is not None:
        memory.kind = body.kind
    if body.tags is not None:
        memory.tags = ",".join(body.tags)
    if body.importance is not None:
        memory.importance = max(1, min(3, body.importance))
    db.commit()
    return {"memory": memory_dict(memory)}


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    memory = db.get(Memory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found")
    db.delete(memory)
    db.commit()
    audit(db, user.id, "memory.delete", memory_id)
    return {"ok": True}


@router.get("/export")
def export_memory(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    rows = db.query(Memory).filter(Memory.user_id == user.id).all()
    import json

    payload = json.dumps(
        {"exported_at": "now", "user": user.email, "memories": [memory_dict(m) for m in rows]},
        indent=2,
    )
    return Response(
        payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="nova-memory.json"'},
    )
