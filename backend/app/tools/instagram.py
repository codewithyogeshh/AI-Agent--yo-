"""Instagram publishing via the official Meta Graph API.

Real constraint, stated plainly: the Graph API only accepts media the platform
can fetch from a public HTTPS URL, and only Business/Creator accounts linked to
a Page can publish. When that is unavailable the tool says so and offers the
manual path instead of pretending.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..config import settings
from ..models import ContentItem, Secret
from ..security import decrypt_value
from ..services import managed_social
from .base import ToolContext, ToolResult, tool
from .publishing import publish_via_managed

GRAPH = "https://graph.facebook.com/v21.0"


def _token(ctx: ToolContext) -> str:
    row = ctx.db.query(Secret).filter(Secret.user_id == ctx.user.id, Secret.name == "instagram.access_token").first()
    return decrypt_value(row.ciphertext) if row else ""


def _ig_user_id(ctx: ToolContext) -> str:
    row = ctx.db.query(Secret).filter(Secret.user_id == ctx.user.id, Secret.name == "instagram.user_id").first()
    return decrypt_value(row.ciphertext) if row else ""


@tool(
    name="instagram.publish",
    description="Publish a Reel or image post to the connected Instagram Business account. Requires approval.",
    category="instagram",
    params={
        "content_id": {"type": "string", "required": True},
        "caption": {"type": "string", "required": False},
    },
    risk="blocked",
    requires=["instagram"],
)
async def instagram_publish(ctx: ToolContext, content_id: str, caption: str = "") -> ToolResult:
    item = ctx.db.get(ContentItem, content_id)
    if item is None or item.user_id != ctx.user.id:
        return ToolResult(False, "Content item not found", verified=False)
    video = Path(item.asset_path) if item.asset_path else None
    if not video or not video.exists():
        return ToolResult(False, "No rendered video attached to this content item", verified=False)
    text = caption or item.caption or item.title

    managed = await managed_social.connected_platforms(ctx.db, ctx.user)
    if "instagram" in managed:
        return await publish_via_managed(
            ctx, item, "instagram", title=(text or item.title or "NOVA")[:2200]
        )

    token = _token(ctx)
    ig_user = _ig_user_id(ctx)
    if not token or not ig_user:
        return ToolResult(
            False,
            "Instagram is not connected. Use Integrations → One-click connect, or link a Business/Creator "
            "account to a Facebook Page with instagram_content_publish permission.",
            verified=False,
            setup_required="instagram",
        )

    public_base = getattr(settings, "public_base_url", "")
    if not public_base:
        return ToolResult(
            False,
            "Instagram must fetch the media from a public HTTPS URL. Set PUBLIC_BASE_URL to a publicly reachable "
            f"backend origin, or download the rendered file and post it manually. File: {video.name if video else 'none'}",
            verified=False,
            setup_required="instagram",
        )

    media_url = f"{public_base.rstrip('/')}/api/content/{item.id}/asset"
    ctx.emit("tool", "Creating the Instagram media container", {"content_id": item.id})
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            create = await client.post(
                f"{GRAPH}/{ig_user}/media",
                data={
                    "media_type": "REELS",
                    "video_url": media_url,
                    "caption": text[:2200],
                    "share_to_feed": "true",
                    "access_token": token,
                },
            )
            if create.status_code >= 400:
                return ToolResult(False, f"Instagram container failed: {create.text[:300]}", verified=False)
            creation_id = create.json().get("id")

            import asyncio

            status = "IN_PROGRESS"
            for _ in range(30):
                await asyncio.sleep(5)
                check = await client.get(
                    f"{GRAPH}/{creation_id}", params={"fields": "status_code", "access_token": token}
                )
                status = check.json().get("status_code", "")
                if status in {"FINISHED", "ERROR", "EXPIRED"}:
                    break
            if status != "FINISHED":
                return ToolResult(False, f"Instagram processing ended in state {status or 'unknown'}", verified=False)

            publish = await client.post(
                f"{GRAPH}/{ig_user}/media_publish",
                data={"creation_id": creation_id, "access_token": token},
            )
            if publish.status_code >= 400:
                return ToolResult(False, f"Instagram publish failed: {publish.text[:300]}", verified=False)
            media_id = publish.json().get("id", "")
    except Exception as exc:
        return ToolResult(False, f"Instagram publish error: {exc}", verified=False)

    item.status = "published"
    item.external_id = media_id
    from ..models import utcnow

    item.published_at = utcnow()
    ctx.db.commit()
    return ToolResult(
        True,
        f"Published to Instagram (media id {media_id})",
        {"media_id": media_id},
        verified=bool(media_id),
    )


@tool(
    name="instagram.analytics",
    description="Read connected Instagram account insights.",
    category="instagram",
    params={},
    requires=["instagram"],
)
async def instagram_analytics(ctx: ToolContext) -> ToolResult:
    token = _token(ctx)
    ig_user = _ig_user_id(ctx)
    if not token or not ig_user:
        return ToolResult(False, "Instagram is not connected.", verified=False, setup_required="instagram")
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            res = await client.get(
                f"{GRAPH}/{ig_user}",
                params={
                    "fields": "username,followers_count,media_count",
                    "access_token": token,
                },
            )
            if res.status_code >= 400:
                return ToolResult(False, f"Instagram API {res.status_code}: {res.text[:250]}", verified=False)
            profile = res.json()
    except Exception as exc:
        return ToolResult(False, f"Instagram analytics failed: {exc}", verified=False)
    return ToolResult(
        True,
        f"@{profile.get('username', '')}: {profile.get('followers_count', '?')} followers · {profile.get('media_count', '?')} posts",
        profile,
    )
