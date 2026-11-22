"""Integration status, OAuth connect/disconnect and connectivity tests."""
from __future__ import annotations

import json
import time
from typing import List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agent import llm
from ..config import settings
from ..db import get_db
from ..models import Secret, User
from ..security import audit, encrypt_value, get_current_user
from ..services import google_api, managed_social, media, whatsapp
from ..services.integration_registry import (
    get_provider, has_token, integration_status, token_names, upsert_status,
)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

FRONTEND = settings.cors_origins[0] if settings.cors_origins else "http://localhost:3000"


@router.get("")
async def list_integrations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    managed_state = await managed_social.status(db, user)
    links = managed_state.get("connections") or {}
    providers = integration_status(db, user)
    for provider in providers:
        link = links.get(provider["id"])
        provider["managed"] = bool(link)
        provider["managed_handle"] = (link or {}).get("handle", "")
        provider["channel"] = "direct" if provider["status"] == "connected" else ("managed" if link else "none")
        provider["effective_status"] = (
            "connected" if provider["status"] == "connected" or link else provider["status"]
        )
    return {
        "integrations": providers,
        "managed": managed_state,
        "whatsapp": {
            "configured": whatsapp.configured(),
            "allowed_numbers": settings.whatsapp_allowed,
            "webhook_url": f"{settings.public_base_url.rstrip('/')}/api/whatsapp/webhook" if settings.public_base_url else "/api/whatsapp/webhook",
            "signature_enforced": bool(settings.whatsapp_app_secret),
        },
        "ai": llm.capabilities(),
        "media": media.capabilities(),
    }


@router.get("/{provider}/authorize")
def authorize(
    provider: str, user: User = Depends(get_current_user)
) -> dict:
    if provider not in {"google", "youtube"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only Google-based providers use the OAuth redirect flow here")
    if not google_api.configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set on the backend. Add them and restart.",
        )
    return {"url": google_api.auth_url(provider, state=f"{provider}:{user.id}")}


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...), state: str = Query("google"), db: Session = Depends(get_db)
) -> RedirectResponse:
    provider = state.split(":")[0] if ":" in state else "google"
    user_id = state.split(":", 1)[1] if ":" in state else ""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown OAuth state — start the flow again")
    try:
        await google_api.exchange_code(db, user, code, provider)
        upsert_status(db, user, provider, "connected")
        target = f"{FRONTEND}/integrations?connected={provider}"
    except Exception as exc:  # noqa: BLE001
        upsert_status(db, user, provider, "error", str(exc))
        target = f"{FRONTEND}/integrations?error={provider}"
    return RedirectResponse(target)


def _store(db: Session, user: User, name: str, value: str) -> None:
    row = db.query(Secret).filter(Secret.user_id == user.id, Secret.name == name).first()
    if row is None:
        row = Secret(user_id=user.id, name=name)
        db.add(row)
    row.ciphertext = encrypt_value(value)
    db.commit()


@router.get("/instagram/authorize")
def instagram_authorize(user: User = Depends(get_current_user)) -> dict:
    if not (settings.meta_app_id and settings.meta_app_secret):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "META_APP_ID / META_APP_SECRET are not configured")
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "state": user.id,
        "scope": "instagram_basic,instagram_content_publish,pages_show_list,business_management",
        "response_type": "code",
    }
    return {"url": f"https://www.facebook.com/v21.0/dialog/oauth?{urlencode(params)}"}


@router.get("/instagram/callback")
async def instagram_callback(
    code: str = Query(...), state: str = Query(""), db: Session = Depends(get_db)
) -> RedirectResponse:
    user = db.get(User, state)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown state — start the flow again")
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            token_res = await client.post(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                data={
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "redirect_uri": settings.meta_redirect_uri,
                    "code": code,
                },
            )
            token_res.raise_for_status()
            short_token = token_res.json().get("access_token", "")
            pages = await client.get(
                "https://graph.facebook.com/v21.0/me/accounts",
                params={"access_token": short_token, "fields": "id,name,access_token,instagram_business_account"},
            )
            pages.raise_for_status()
            linked = None
            for page in pages.json().get("data", []):
                if page.get("instagram_business_account"):
                    linked = page
                    break
            if not linked:
                raise RuntimeError(
                    "No Instagram Business account linked to a Facebook Page was found. "
                    "Convert the Instagram account to Business/Creator and link a Page."
                )
        _store(db, user, "instagram.access_token", linked["access_token"])
        _store(db, user, "instagram.user_id", linked["instagram_business_account"]["id"])
        _store(db, user, "instagram.page_id", linked["id"])
        upsert_status(db, user, "instagram", "connected")
        target = f"{FRONTEND}/integrations?connected=instagram"
    except Exception as exc:  # noqa: BLE001
        upsert_status(db, user, "instagram", "error", str(exc))
        target = f"{FRONTEND}/integrations?error=instagram"
    return RedirectResponse(target)


@router.post("/{provider}/disconnect")
def disconnect(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.query(Secret).filter(Secret.user_id == user.id, Secret.name.in_(token_names(provider))).all()
    for row in rows:
        db.delete(row)
    if provider == "instagram":
        for row in db.query(Secret).filter(Secret.user_id == user.id, Secret.name.like("instagram.%")).all():
            db.delete(row)
    db.commit()
    upsert_status(db, user, provider, "not_configured")
    audit(db, user.id, "integration.disconnect", provider)
    return {"ok": True}


@router.post("/{provider}/test")
async def test_provider(
    provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    spec = get_provider(provider)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider")
    links = await managed_social.connected_platforms(db, user)
    if provider in links:
        return {
            "ok": True,
            "detail": f"Linked via Upload-Post as {links[provider].get('handle') or 'the connected account'}",
            "channel": "managed",
        }
    if not has_token(db, user, provider) and provider != "whatsapp":
        return {"ok": False, "detail": "Not connected yet. Complete the authorisation flow first."}
    try:
        if provider == "google":
            profile = await google_api.profile(db, user)
            return {"ok": True, "detail": f"Connected as {profile.get('email', 'unknown')}"}
        if provider == "youtube":
            from ..tools.youtube import youtube_analytics
            from ..tools.base import ToolContext

            ctx = ToolContext(db=db, user=user, task=None, emit=lambda *a, **k: None)
            result = await youtube_analytics(ctx)
            return {"ok": result.ok, "detail": result.summary}
        if provider == "instagram":
            from ..tools.base import ToolContext
            from ..tools.instagram import instagram_analytics

            ctx = ToolContext(db=db, user=user, task=None, emit=lambda *a, **k: None)
            result = await instagram_analytics(ctx)
            return {"ok": result.ok, "detail": result.summary}
        if provider == "whatsapp":
            ok = whatsapp.configured()
            return {
                "ok": ok,
                "detail": "Cloud API credentials present." if ok else "WHATSAPP_TOKEN / PHONE_NUMBER_ID missing.",
            }
    except Exception as exc:  # noqa: BLE001
        upsert_status(db, user, provider, "error", str(exc))
        return {"ok": False, "detail": str(exc)[:400]}
    return {"ok": False, "detail": "No test available for this provider"}


# ------------------------------------------------------- one-click managed connect
class ManagedKeyBody(BaseModel):
    # Upload-Post keys are long signed tokens, often 200-600 characters; a
    # tighter cap rejected real keys with an unreadable 422 before they were
    # ever checked with the provider.
    api_key: str = Field(min_length=10, max_length=4096)


class ManagedConnectBody(BaseModel):
    platforms: List[str] = Field(default_factory=lambda: ["youtube", "instagram"])


class ManagedPlatformBody(BaseModel):
    platform: str


@router.get("/managed")
async def managed_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return await managed_social.status(db, user)


@router.post("/managed/key")
async def save_managed_key(
    body: ManagedKeyBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    try:
        await managed_social.validate_key(body.api_key.strip())
    except managed_social.ManagedSocialError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    managed_social.store_api_key(db, user, body.api_key)
    return await managed_social.status(db, user)


@router.post("/managed/connect")
async def managed_connect(
    body: ManagedConnectBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    try:
        url = await managed_social.connect_url(
            db, user, body.platforms, f"{FRONTEND}/integrations?managed=connected"
        )
    except managed_social.ManagedSocialError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"url": url}


@router.post("/managed/accounts/disconnect")
async def managed_disconnect(
    body: ManagedPlatformBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    try:
        await managed_social.disconnect(db, user, body.platform)
    except managed_social.ManagedSocialError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"ok": True}
