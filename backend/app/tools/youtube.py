"""YouTube publishing + analytics via official Google APIs.

Upload uses the resumable protocol and always requires approval. Nothing is
published when the channel is not connected.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..models import ContentItem
from ..services import google_api, managed_social
from .base import ToolContext, ToolResult, tool
from .publishing import publish_via_managed

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


async def _token(ctx: ToolContext) -> Optional[str]:
    return await google_api.access_token(ctx.db, ctx.user, "youtube")


@tool(
    name="youtube.upload",
    description="Upload a produced video to YouTube with title, description, tags and thumbnail. Requires approval.",
    category="youtube",
    params={
        "content_id": {"type": "string", "required": True},
        "privacy": {"type": "string", "required": False, "description": "private | unlisted | public"},
        "publish_at": {"type": "string", "required": False, "description": "ISO datetime for scheduled release"},
    },
    risk="blocked",
    requires=["youtube"],
)
async def youtube_upload(
    ctx: ToolContext, content_id: str, privacy: str = "private", publish_at: str = ""
) -> ToolResult:
    item = ctx.db.get(ContentItem, content_id)
    if item is None or item.user_id != ctx.user.id:
        return ToolResult(False, "Content item not found", verified=False)
    video = Path(item.asset_path) if item.asset_path else None
    if not video or not video.exists() or video.stat().st_size < 10_000:
        return ToolResult(False, "No rendered video file is attached to this content item", verified=False)

    meta = {}
    try:
        meta = json.loads(item.metadata_json or "{}")
    except json.JSONDecodeError:
        pass

    privacy = privacy if privacy in {"private", "unlisted", "public"} else "private"

    managed = await managed_social.connected_platforms(ctx.db, ctx.user)
    if "youtube" in managed:
        return await publish_via_managed(
            ctx,
            item,
            "youtube",
            title=(item.title or "Untitled")[:100],
            description=item.description or item.caption or "",
            tags=[str(tag) for tag in (meta.get("tags") or [])][:15],
            privacy=privacy,
            publish_at=publish_at,
        )

    if not google_api.configured():
        return ToolResult(
            False,
            "YouTube is not connected. Use Integrations → One-click connect, or configure "
            "GOOGLE_CLIENT_ID/SECRET with the YouTube scopes and connect the channel.",
            verified=False,
            setup_required="youtube",
        )
    token = await _token(ctx)
    if not token:
        return ToolResult(False, "YouTube authorisation missing or expired — reconnect Google.", verified=False, setup_required="youtube")

    body: Dict[str, Any] = {
        "snippet": {
            "title": (item.title or "Untitled")[:100],
            "description": (item.description or item.caption or "")[:4900],
            "tags": (meta.get("tags") or [])[:15],
            "categoryId": "28",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at
        body["status"]["privacyStatus"] = "private"

    ctx.emit("tool", f"Uploading “{item.title[:50]}” to YouTube ({privacy})", {"content_id": item.id})
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            init = await client.post(
                UPLOAD_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(video.stat().st_size),
                },
                json=body,
            )
            if init.status_code >= 400:
                return ToolResult(False, f"YouTube upload init failed {init.status_code}: {init.text[:300]}", verified=False)
            session_url = init.headers.get("location")
            if not session_url:
                return ToolResult(False, "YouTube did not return an upload session", verified=False)
            with video.open("rb") as handle:
                upload = await client.put(
                    session_url,
                    content=handle.read(),
                    headers={"Content-Type": "video/mp4", "Content-Length": str(video.stat().st_size)},
                )
            if upload.status_code >= 400:
                return ToolResult(False, f"YouTube upload failed {upload.status_code}: {upload.text[:300]}", verified=False)
            video_id = upload.json().get("id", "")
    except Exception as exc:
        return ToolResult(False, f"YouTube upload error: {exc}", verified=False)

    thumbnail_note = ""
    thumb = Path(item.thumb_path) if item.thumb_path else None
    if video_id and thumb and thumb.exists():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                res = await client.post(
                    f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
                    content=thumb.read_bytes(),
                )
            thumbnail_note = "" if res.status_code < 400 else f" (thumbnail failed: {res.status_code})"
        except Exception as exc:
            thumbnail_note = f" (thumbnail failed: {exc})"

    item.status = "published"
    item.external_id = video_id
    from ..models import utcnow

    item.published_at = utcnow()
    ctx.db.commit()
    return ToolResult(
        True,
        f"Uploaded to YouTube as {privacy}: https://youtu.be/{video_id}{thumbnail_note}",
        {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "privacy": privacy},
        verified=bool(video_id),
        artifacts=[{"kind": "link", "title": item.title[:70], "url": f"https://youtu.be/{video_id}"}],
    )


@tool(
    name="youtube.analytics",
    description="Read channel and recent video performance from YouTube.",
    category="youtube",
    params={"days": {"type": "integer", "required": False}},
    requires=["youtube"],
)
async def youtube_analytics(ctx: ToolContext, days: int = 28) -> ToolResult:
    if not google_api.configured():
        return ToolResult(False, "YouTube is not connected.", verified=False, setup_required="youtube")
    token = await _token(ctx)
    if not token:
        return ToolResult(False, "YouTube authorisation missing — reconnect Google.", verified=False, setup_required="youtube")
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            res = await client.get(
                f"{YOUTUBE_API}/channels",
                params={"part": "snippet,statistics", "mine": "true"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if res.status_code >= 400:
                return ToolResult(False, f"YouTube API {res.status_code}: {res.text[:250]}", verified=False)
            data = res.json()
    except Exception as exc:
        return ToolResult(False, f"YouTube analytics failed: {exc}", verified=False)

    channels = data.get("items", [])
    if not channels:
        return ToolResult(False, "No YouTube channel found for this account", verified=False)
    channel = channels[0]
    stats = channel.get("statistics", {})
    return ToolResult(
        True,
        f"Channel “{channel.get('snippet', {}).get('title', '')}”: {stats.get('subscriberCount', '?')} subscribers, "
        f"{stats.get('viewCount', '?')} views",
        {
            "channel": channel.get("snippet", {}).get("title"),
            "subscribers": stats.get("subscriberCount"),
            "views": stats.get("viewCount"),
            "videos": stats.get("videoCount"),
        },
    )
