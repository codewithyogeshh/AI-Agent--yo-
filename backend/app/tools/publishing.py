"""One mapping from a managed publish outcome to the tool contract.

Both YouTube and Instagram use the same managed provider, so the result
handling, content-item bookkeeping and artifacts live here once.
"""
from __future__ import annotations

from typing import List, Optional

from ..models import ContentItem, utcnow
from ..services import managed_social
from .base import ToolContext, ToolResult

# platform -> (in-progress verb, completed verb); the display name lives in the service.
VERBS = {"youtube": ("Uploading", "Uploaded to"), "instagram": ("Publishing", "Published to")}


async def _notify_failure(ctx: ToolContext, platform: str, name: str, reason: str) -> None:
    """Best-effort WhatsApp/dashboard alert; never raises into the publish path."""
    try:
        from ..services import notifications

        await notifications.notify_user(
            ctx.db,
            ctx.user,
            f"{name} publish failed",
            reason,
            level="error",
            meta={"platform": platform, "channel": "managed"},
        )
    except Exception:  # noqa: BLE001 - notifications must not break publishing
        pass


async def publish_via_managed(
    ctx: ToolContext,
    item: ContentItem,
    platform: str,
    *,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    privacy: str = "",
    publish_at: str = "",
) -> ToolResult:
    name = managed_social.SUPPORTED[platform]
    in_progress, completed = VERBS[platform]
    # Surface a cached quota warning (low/exhausted) even when the user never
    # opens Integrations; best-effort and level-transition gated.
    try:
        cached = managed_social.cached_quota(ctx.user.id)
        if cached is not None:
            await managed_social.notify_quota_transition(ctx.db, ctx.user, cached)
    except Exception:  # noqa: BLE001 - never break the publish path
        pass
    ctx.emit(
        "tool",
        f"{in_progress} “{(item.title or 'Untitled')[:50]}” to {name} through the managed connection",
        {"content_id": item.id, "channel": "managed"},
    )
    try:
        outcome = await managed_social.publish_video(
            ctx.db,
            ctx.user,
            item.asset_path,
            platform,
            title=title,
            description=description,
            tags=tags,
            thumbnail_path=item.thumb_path or "",
            external_id=item.id,
            idempotency_key=f"nova-{item.id}-{platform}",
            privacy=privacy,
            publish_at=publish_at,
        )
    except managed_social.ManagedSocialError as exc:
        await _notify_failure(ctx, platform, name, str(exc))
        return ToolResult(False, f"{name} publishing failed: {exc}", verified=False)

    if not outcome.ok:
        await _notify_failure(ctx, platform, name, outcome.error)
        return ToolResult(False, f"{name} publishing failed: {outcome.error}", verified=False)
    if outcome.queued:
        # Leave queued/background items pending until they are confirmed.
        return ToolResult(
            True,
            f"{name} publish queued with Upload-Post (request {outcome.request_id or '—'}) — "
            "it finishes in the background; the item stays pending until confirmed.",
            {"request_id": outcome.request_id, "channel": "managed"},
            verified=False,
        )

    item.status = "published"
    item.external_id = outcome.post_id
    item.published_at = utcnow()
    ctx.db.commit()
    suffix = f" as {privacy}" if privacy else ""
    link = f": {outcome.url}" if outcome.url else ""
    return ToolResult(
        True,
        f"{completed} {name} through the managed connection{suffix}{link}",
        {"post_id": outcome.post_id, "url": outcome.url, "channel": "managed"},
        verified=outcome.verified,
        artifacts=[{"kind": "link", "title": item.title[:70], "url": outcome.url}] if outcome.url else [],
    )
