"""Workspace files API — sandboxed per user, with signed download URLs."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import MediaAsset, User
from ..security import decode_token, get_current_user
from ..serializers import asset_dict
from ..tools.files import TEXT_SUFFIXES, safe_path
from ..tools.base import ToolContext

router = APIRouter(prefix="/api/files", tags=["files"])


def _ctx(db: Session, user: User) -> ToolContext:
    return ToolContext(db=db, user=user, task=None, emit=lambda *a, **k: None)


@router.get("")
def list_files(
    path: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    ctx = _ctx(db, user)
    try:
        target = safe_path(ctx, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    entries = []
    if target.exists() and target.is_dir():
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:400]:
            stat = child.stat()
            entries.append({
                "name": child.name,
                "path": str(child.relative_to(ctx.user_dir)),
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size,
                "modified": __import__("datetime").datetime.utcfromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "previewable": child.suffix.lower() in TEXT_SUFFIXES,
            })
    assets = (
        db.query(MediaAsset).filter(MediaAsset.user_id == user.id).order_by(desc(MediaAsset.created_at)).limit(100).all()
    )
    return {"path": path, "entries": entries, "assets": [asset_dict(a) for a in assets]}


@router.get("/content")
def read_file(
    path: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    ctx = _ctx(db, user)
    try:
        target = safe_path(ctx, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if target.stat().st_size > 500_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large to preview")
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Preview supported for text files only")
    return {"path": path, "content": target.read_text(encoding="utf-8", errors="replace")}


@router.post("/upload")
async def upload(
    file: UploadFile = File(...), path: str = "",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    ctx = _ctx(db, user)
    payload = await file.read()
    if len(payload) > 60 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Max upload is 60 MB")
    name = Path(file.filename or "upload.bin").name
    try:
        folder = safe_path(ctx, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_bytes(payload)
    asset = MediaAsset(
        user_id=user.id, name=name, path=str(target), mime=file.content_type or "application/octet-stream",
        size=len(payload), kind="video" if (file.content_type or "").startswith("video") else "file",
    )
    db.add(asset)
    db.commit()
    return {"asset": asset_dict(asset)}


@router.get("/artifact")
def artifact(path: str, t: str = Query(""), db: Session = Depends(get_db)):
    """Serve a task artifact by absolute path, but only inside the caller's workspace."""
    try:
        payload = decode_token(t)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Valid asset token required")
    from ..config import settings
    from ..models import User as UserModel

    user = db.get(UserModel, payload.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    root = (Path(settings.workspace_dir) / user.id).resolve()
    target = Path(path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Artifact is outside your workspace")
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
    return FileResponse(target, filename=target.name)


@router.get("/download")
def download(
    path: str, t: str = Query(""), db: Session = Depends(get_db)
):
    try:
        payload = decode_token(t)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Valid asset token required")
    from ..models import User as UserModel

    user = db.get(UserModel, payload.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    ctx = _ctx(db, user)
    try:
        target = safe_path(ctx, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(target, filename=target.name)
