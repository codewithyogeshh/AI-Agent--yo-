"""Security primitives: password hashing, JWT sessions, encrypted token storage,
rate limiting and webhook signature validation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditLog, User

PBKDF2_ROUNDS = 240_000
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt_b64, digest_b64 = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


# ---------------------------------------------------------------- JWT
def create_access_token(user_id: str, email: str, role: str = "owner") -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + settings.access_token_minutes * 60,
        "iss": "nova",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"], issuer="nova")


def _decode_supabase(token: str) -> Optional[Dict[str, Any]]:
    if not settings.supabase_jwt_secret:
        return None
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": True},
        )
    except jwt.PyJWTError:
        return None


def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    token = creds.credentials if creds else request.cookies.get("nova_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    user: Optional[User] = None
    try:
        payload = decode_token(token)
        user = db.get(User, payload.get("sub"))
    except jwt.PyJWTError:
        payload = _decode_supabase(token)
        if payload:
            email = (payload.get("email") or "").lower()
            user = db.query(User).filter(User.email == email).first()
            if user is None and email:
                user = User(email=email, name=email.split("@")[0], password_hash="!supabase")
                db.add(user)
                db.commit()
                db.refresh(user)

    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
    return user


def audit(db: Session, user_id: Optional[str], action: str, target: str = "", ip: str = "",
          level: str = "info", data: Optional[dict] = None, actor: str = "user") -> None:
    db.add(AuditLog(user_id=user_id, action=action, target=target, ip=ip, level=level,
                    actor=actor, data_json=json.dumps(data or {}, default=str)))
    db.commit()


# ---------------------------------------------------------------- secrets at rest
def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_value(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


# ---------------------------------------------------------------- rate limiting
class RateLimiter:
    """Small in-process sliding window. Swap for Redis when running multi-node."""

    def __init__(self) -> None:
        self._hits: Dict[str, list[float]] = {}

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.time()
        bucket = [t for t in self._hits.get(key, []) if now - t < window_seconds]
        if len(bucket) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded, slow down")
        bucket.append(now)
        self._hits[key] = bucket


rate_limiter = RateLimiter()


def verify_whatsapp_signature(raw_body: bytes, signature_header: str) -> bool:
    if not settings.whatsapp_app_secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


def verify_desktop_token(token: str) -> bool:
    return bool(settings.desktop_bridge_token) and hmac.compare_digest(token, settings.desktop_bridge_token)
