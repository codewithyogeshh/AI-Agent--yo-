"""Authentication: first-run owner registration, JWT login, profile."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..security import (
    audit, create_access_token, get_current_user, hash_password, rate_limiter, verify_password,
)
from ..serializers import user_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str = ""
    phone: str = ""


class LoginBody(BaseModel):
    email: EmailStr
    password: str


@router.get("/status")
def auth_status(db: Session = Depends(get_db)) -> dict:
    count = db.query(User).count()
    return {
        "initialised": count > 0,
        "registration_open": count == 0,
        "supabase_enabled": bool(settings.supabase_jwt_secret),
        "provider": "supabase" if settings.supabase_jwt_secret else "local",
    }


@router.post("/register")
def register(body: RegisterBody, request: Request, db: Session = Depends(get_db)) -> dict:
    if db.query(User).count() > 0:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed. Ask the owner to create the account.")
    if len(body.password) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use a password of at least 10 characters")
    user = User(
        email=body.email.lower(),
        name=body.name or body.email.split("@")[0],
        password_hash=hash_password(body.password),
        phone=body.phone,
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(db, user.id, "auth.register", user.email, request.client.host if request.client else "")
    return {"token": create_access_token(user.id, user.email, user.role), "user": user_dict(user)}


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)) -> dict:
    ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"login:{ip}", 10, 60)
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        audit(db, user.id if user else None, "auth.login_failed", body.email, ip, level="warning")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    audit(db, user.id, "auth.login", user.email, ip)
    return {"token": create_access_token(user.id, user.email, user.role), "user": user_dict(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return user_dict(user)


@router.patch("/me")
def update_me(
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if "name" in payload:
        user.name = str(payload["name"])[:120]
    if "phone" in payload:
        user.phone = str(payload["phone"])[:32]
    if "timezone" in payload:
        user.timezone = str(payload["timezone"])[:64]
    db.commit()
    return user_dict(user)


@router.post("/change-password")
def change_password(
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    current = str(payload.get("current_password", ""))
    new = str(payload.get("new_password", ""))
    if not verify_password(current, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is wrong")
    if len(new) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "New password must be at least 10 characters")
    user.password_hash = hash_password(new)
    db.commit()
    audit(db, user.id, "auth.password_changed", user.email)
    return {"ok": True}
