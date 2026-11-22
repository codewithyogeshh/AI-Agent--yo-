"""One-click social connect through Upload-Post's verified platform apps.

Why this exists: connecting YouTube or Instagram directly requires the user to
create a Google Cloud / Meta developer app first. Upload-Post already owns
verified OAuth apps, so the owner only adds one API key and then opens a hosted
connect page — the platform consent screens are the only steps left.

The key is stored encrypted per user (a fallback env var is supported). Nothing
here publishes anything; it links accounts and reports what is linked.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Secret, User
from ..security import audit, decrypt_value, encrypt_value

BASE_URL = "https://api.upload-post.com/api"
KEY_SECRET = "managed_social.api_key"
SUPPORTED = {"youtube": "YouTube", "instagram": "Instagram"}

# Tests inject an httpx.MockTransport here; production leaves it None.
transport: Optional[httpx.AsyncBaseTransport] = None

# Platform links change rarely; cache them so a publish or page load does not
# hit the provider twice in a row. Invalidated on connect/disconnect.
CACHE_TTL_SECONDS = 45.0
QUOTA_TTL_SECONDS = 60.0
_link_cache: Dict[str, Tuple[float, Dict[str, Dict[str, Any]]]] = {}
_quota_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_quota_notified: Dict[str, str] = {}  # user_id -> last notified level


def invalidate(user_id: str) -> None:
    _link_cache.pop(user_id, None)
    _quota_cache.pop(user_id, None)
    _quota_notified.pop(user_id, None)


class ManagedSocialError(RuntimeError):
    """Provider or configuration failure, with a message safe to show a user."""


YOUTUBE_PRIVACY = {"public", "unlisted", "private"}


@dataclass
class PublishResult:
    """Normalised outcome of one managed publish."""

    ok: bool
    url: str = ""
    post_id: str = ""
    request_id: str = ""
    queued: bool = False
    error: str = ""
    verified: bool = False


def _response_json(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001 - provider error bodies are not always JSON
        return {}
    return data if isinstance(data, dict) else {}


def _error_detail(response: httpx.Response) -> str:
    body = _response_json(response)
    return str(body.get("error_code") or body.get("message") or body.get("error") or "") or response.text[:200]


def api_key(db: Session, user: User) -> str:
    row = (
        db.query(Secret)
        .filter(Secret.user_id == user.id, Secret.name == KEY_SECRET)
        .first()
    )
    if row is not None and row.ciphertext:
        try:
            return decrypt_value(row.ciphertext)
        except Exception:  # noqa: BLE001 - unreadable key means "not configured"
            return ""
    return settings.upload_post_api_key


def store_api_key(db: Session, user: User, key: str) -> None:
    value = (key or "").strip()
    row = (
        db.query(Secret)
        .filter(Secret.user_id == user.id, Secret.name == KEY_SECRET)
        .first()
    )
    if row is None:
        row = Secret(user_id=user.id, name=KEY_SECRET)
        db.add(row)
    row.ciphertext = encrypt_value(value)
    db.commit()
    audit(db, user.id, "integration.managed_key_saved", "upload-post")


async def _call(method: str, path: str, key: str, payload: Optional[dict] = None) -> Dict[str, Any]:
    if not key:
        raise ManagedSocialError("No Upload-Post API key yet. Add one to enable one-click connect.")
    url = f"{BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30, transport=transport) as client:
        response = await client.request(
            method, url, headers={"Authorization": f"Apikey {key}"}, json=payload
        )
    if response.status_code == 401:
        raise ManagedSocialError("Upload-Post rejected the API key. Check it and save it again.")
    if response.status_code >= 400:
        raise ManagedSocialError(
            f"Upload-Post error {response.status_code}: {_error_detail(response) or 'request failed'}"
        )
    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        raise ManagedSocialError("Upload-Post returned a non-JSON response") from exc
    if isinstance(data, dict) and data.get("success") is False:
        raise ManagedSocialError(f"Upload-Post refused the request: {data.get('message') or data.get('error_code') or 'unknown'}")
    return data if isinstance(data, dict) else {"data": data}


async def validate_key(key: str) -> Dict[str, Any]:
    """Cheap authenticated read used to prove a pasted key works."""
    return await _call("GET", "/uploadposts/users", key)


async def list_profiles(db: Session, user: User) -> List[Dict[str, Any]]:
    data = await _call("GET", "/uploadposts/users", api_key(db, user))
    profiles = data.get("profiles")
    return profiles if isinstance(profiles, list) else []


async def ensure_profile(db: Session, user: User, display_name: str = "NOVA") -> Dict[str, Any]:
    """Return this NOVA user's managed profile, creating it on first use."""
    username = user.id
    for profile in await list_profiles(db, user):
        if profile.get("username") == username:
            return profile
    try:
        data = await _call(
            "POST",
            "/uploadposts/users",
            api_key(db, user),
            {"username": username, "display_name": display_name[:100]},
        )
    except ManagedSocialError as exc:
        # A concurrent call may have created it; re-read before failing.
        for profile in await list_profiles(db, user):
            if profile.get("username") == username:
                return profile
        raise exc
    profile = data.get("profile")
    return profile if isinstance(profile, dict) else {"username": username, "social_accounts": {}}


async def connect_url(db: Session, user: User, platforms: List[str], redirect_url: str = "") -> str:
    """Hosted page where the user taps each platform and approves its consent screen."""
    wanted = [name for name in platforms if name in SUPPORTED]
    if not wanted:
        raise ManagedSocialError(f"Choose at least one platform ({', '.join(SUPPORTED)}).")
    await ensure_profile(db, user)
    payload: Dict[str, Any] = {
        "username": user.id,
        "platforms": wanted,
        "connect_title": "Connect your accounts to NOVA",
        "connect_description": "Approve the platform account NOVA may post to. No developer setup needed.",
        "show_calendar": False,
        "language": "en",
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url
    data = await _call("POST", "/uploadposts/users/generate-jwt", api_key(db, user), payload)
    url = data.get("access_url") or ""
    if not url:
        raise ManagedSocialError("Upload-Post did not return a connect link.")
    return url


def connections(profile: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map platform -> {handle, display_name} for genuinely connected accounts."""
    accounts = (profile or {}).get("social_accounts") or {}
    linked: Dict[str, Dict[str, Any]] = {}
    if not isinstance(accounts, dict):
        return linked
    for platform, details in accounts.items():
        if platform not in SUPPORTED or not details:
            continue
        if isinstance(details, dict):
            linked[platform] = {
                "handle": details.get("handle") or details.get("username") or "",
                "display_name": details.get("display_name") or "",
            }
        else:
            linked[platform] = {"handle": "", "display_name": str(details)[:80]}
    return linked


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _empty_quota(plan: str = "") -> Dict[str, Any]:
    return {
        "available": False,
        "used": None,
        "limit": None,
        "remaining": None,
        "percent": 0.0,
        "resets_at": "",
        "plan": plan,
        "unlimited": False,
        "level": "ok",  # ok | low | exhausted
        "error": "",
    }


def _quota_from(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("api_usage") or payload.get("usage") or {}
    plan = str(payload.get("plan") or "")
    if not isinstance(raw, dict):
        return {**_empty_quota(plan), "error": "Upload-Post did not report upload usage"}
    used = _as_int(raw.get("count", raw.get("used")))
    limit = _as_int(raw.get("limit"))
    if used is None or limit is None:
        return {**_empty_quota(plan), "error": "Upload-Post did not report upload usage"}
    used = max(used, 0)
    if limit <= 0:  # paid plans report unlimited monthly uploads
        return {**_empty_quota(plan), "available": True, "used": used, "unlimited": True}
    remaining = max(limit - used, 0)
    percent = round(min(used / limit * 100, 100.0), 1)
    level = "exhausted" if remaining == 0 else "low" if percent >= 80 else "ok"
    return {
        "available": True,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "percent": percent,
        "resets_at": str(raw.get("last_reset") or raw.get("resets_at") or ""),
        "plan": plan,
        "unlimited": False,
        "level": level,
        "error": "",
    }


async def notify_quota_transition(db: Session, user: User, result: Dict[str, Any]) -> None:
    """Send the level-transition WhatsApp/dashboard warning if needed.

    Best-effort: never raises into the caller. The in-memory ``_quota_notified``
    marker suppresses repeated messages for the same level.
    """
    level = result.get("level", "ok")
    if result.get("available") and level in ("low", "exhausted"):
        if _quota_notified.get(user.id) != level:
            try:
                from . import notifications

                title = (
                    "Upload-Post monthly uploads used up"
                    if level == "exhausted"
                    else "Upload-Post monthly uploads nearly used up"
                )
                body = (
                    f"{result['used']} of {result['limit']} monthly uploads used."
                    + (f" {result['remaining']} left." if result.get("remaining") is not None else "")
                    + (f" Resets {result['resets_at']}." if result.get("resets_at") else "")
                    + " Upgrade the plan in Integrations to avoid publish failures."
                )
                await notifications.notify_user(
                    db,
                    user,
                    title,
                    body,
                    level="error" if level == "exhausted" else "warn",
                    meta={"quota": result},
                )
            except Exception:  # noqa: BLE001 - notifications must not break publishing
                pass
            else:
                _quota_notified[user.id] = level
    elif level == "ok":
        _quota_notified.pop(user.id, None)


async def quota(db: Session, user: User, fresh: bool = False) -> Dict[str, Any]:
    """Monthly upload allowance. Cached briefly; never raises."""
    key = api_key(db, user)
    if not key:
        return _empty_quota()
    cached = _quota_cache.get(user.id)
    if cached and not fresh and time.monotonic() - cached[0] < QUOTA_TTL_SECONDS:
        return cached[1]
    try:
        result = _quota_from(await _call("GET", "/uploadposts/me", key))
    except ManagedSocialError as exc:
        result = {**_empty_quota(), "error": str(exc)[:200]}
    await notify_quota_transition(db, user, result)
    _quota_cache[user.id] = (time.monotonic(), result)
    return result


def cached_quota(user_id: str) -> Optional[Dict[str, Any]]:
    """Recently cached allowance, without spending a request to refresh it.

    Stale entries are ignored so an exhausted reading cannot block publishes
    forever once the monthly reset has passed.
    """
    cached = _quota_cache.get(user_id)
    if not cached or time.monotonic() - cached[0] >= QUOTA_TTL_SECONDS:
        return None
    return cached[1]


def _quota_refusal(quota: Dict[str, Any]) -> str:
    reset = f" It resets on {quota['resets_at']}." if quota.get("resets_at") else ""
    return (
        f"Upload-Post monthly upload allowance is used up "
        f"({quota.get('used')} of {quota.get('limit')} used). Nothing was uploaded — "
        f"upgrade the plan in Integrations or wait for the monthly reset.{reset}"
    )


async def status(db: Session, user: User) -> Dict[str, Any]:
    """Never raises: the dashboard needs a usable answer even when offline."""
    key = api_key(db, user)
    result: Dict[str, Any] = {
        "configured": bool(key),
        "provider": "upload-post",
        "profile_username": user.id,
        "connections": {},
        "platforms": [],
        "quota": _empty_quota(),
        "error": "",
    }
    if not key:
        return result
    result["quota"] = await quota(db, user)
    try:
        profiles = await list_profiles(db, user)
        profile = next((p for p in profiles if p.get("username") == user.id), None)
        result["connections"] = connections(profile)
        _link_cache[user.id] = (time.monotonic(), result["connections"])
    except ManagedSocialError as exc:
        result["error"] = str(exc)[:300]
    result["platforms"] = [
        {
            "id": platform,
            "name": name,
            "connected": platform in result["connections"],
            "handle": result["connections"].get(platform, {}).get("handle", ""),
            "display_name": result["connections"].get(platform, {}).get("display_name", ""),
        }
        for platform, name in SUPPORTED.items()
    ]
    return result


async def disconnect(db: Session, user: User, platform: str) -> None:
    if platform not in SUPPORTED:
        raise ManagedSocialError(f"Unsupported platform “{platform}”.")
    await _call(
        "DELETE",
        "/uploadposts/users/social",
        api_key(db, user),
        {"profile_username": user.id, "social_platform": platform},
    )
    invalidate(user.id)
    audit(db, user.id, "integration.managed_disconnect", platform)


async def connected_platforms(
    db: Session, user: User, fresh: bool = False
) -> Dict[str, Dict[str, Any]]:
    """Linked platforms -> {handle, display_name}. Cached briefly, never raises."""
    now = time.monotonic()
    cached = _link_cache.get(user.id)
    if cached and not fresh and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    links: Dict[str, Dict[str, Any]] = {}
    if api_key(db, user):
        try:
            profiles = await list_profiles(db, user)
            profile = next((row for row in profiles if row.get("username") == user.id), None)
            links = connections(profile)
        except ManagedSocialError:
            links = cached[1] if cached else {}
    _link_cache[user.id] = (now, links)
    return links


async def _verify_public_url(url: str) -> bool:
    """Confirm the provider's returned URL is actually public and reachable.

    A publish is only "complete" once the public page answers successfully;
    otherwise the item stays pending and the caller is told what failed.
    """
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport, follow_redirects=True) as client:
            response = await client.get(url)
    except Exception:  # noqa: BLE001 - unreachable/misconfigured URL is a failed verification
        return False
    return response.status_code == 200


async def publish_video(
    db: Session,
    user: User,
    video_path: str,
    platform: str,
    *,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    thumbnail_path: str = "",
    external_id: str = "",
    idempotency_key: str = "",
    privacy: str = "",
    publish_at: str = "",
) -> PublishResult:
    """Publish one local video to one managed platform.

    `privacy` and `publish_at` apply to YouTube only. Privacy is validated here
    because Upload-Post defaults YouTube to public, so it is never omitted once
    requested. A background job returns `queued=True` with a request id.
    """
    if platform not in SUPPORTED:
        raise ManagedSocialError(f"Unsupported platform “{platform}”.")
    if privacy and privacy not in YOUTUBE_PRIVACY:
        raise ManagedSocialError(
            f"Unsupported YouTube privacy “{privacy}” — use public, unlisted or private."
        )
    path = Path(video_path)
    if not path.exists() or path.stat().st_size == 0:
        raise ManagedSocialError(f"Video file not found: {path.name}")

    # Refuse before streaming anything when the cached allowance is gone. A
    # stale cache (another upload took the last slot) still falls through to
    # the provider's 429 below.
    known = cached_quota(user.id)
    if known and known.get("available") and not known.get("unlimited") and not known.get("remaining"):
        raise ManagedSocialError(_quota_refusal(known))

    form = {
        "user": user.id,
        "title": (title or "Untitled")[:100],
        "description": description[:4900],
        "external_id": external_id[:255],
    }
    if platform == "youtube":
        if privacy:
            form["privacyStatus"] = privacy
        if publish_at:
            form["youtube_publish_at"] = publish_at

    headers = {"Authorization": f"Apikey {api_key(db, user)}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:200]

    thumb = Path(thumbnail_path) if thumbnail_path else None
    files: List[Tuple[str, Tuple[Optional[str], Any, Optional[str]]]] = [
        ("platform[]", (None, platform, None))
    ]
    # Stream the file instead of reading it into memory.
    with path.open("rb") as video:
        files.append(("video", (path.name, video, "video/mp4")))
        if thumb is not None and thumb.exists() and thumb.stat().st_size:
            files.append(("thumbnail", (thumb.name, thumb.read_bytes(), "image/png")))
        for tag in (tags or [])[:15]:
            files.append(("tags[]", (None, str(tag), None)))
        async with httpx.AsyncClient(timeout=600, transport=transport) as client:
            response = await client.post(f"{BASE_URL}/upload", headers=headers, data=form, files=files)

    if response.status_code == 401:
        raise ManagedSocialError("Upload-Post rejected the API key. Save it again in Integrations.")
    if response.status_code == 429:
        usage = _response_json(response).get("usage") or {}
        detail = f" (used {usage.get('count')} of {usage.get('limit')})" if usage else ""
        raise ManagedSocialError(f"Upload-Post monthly limit reached{detail}. Upgrade the plan or retry next cycle.")
    if response.status_code >= 400:
        raise ManagedSocialError(
            f"Upload-Post error {response.status_code}: {_error_detail(response) or 'upload failed'}"
        )

    body = _response_json(response)
    _quota_cache.pop(user.id, None)  # the allowance just changed
    result = (body.get("results") or {}).get(platform) or {}
    request_id = str(body.get("request_id") or "")
    if result.get("success") is False:
        return PublishResult(
            False, error=str(result.get("error") or "the provider reported a failure"), request_id=request_id
        )
    if not result:
        return (
            PublishResult(True, request_id=request_id, queued=True)
            if request_id
            else PublishResult(False, error="the provider returned no result")
        )
    url = str(result.get("url") or "")
    post_id = str(result.get("video_id") or result.get("post_id") or result.get("container_id") or "")
    # Confirm synchronous results are actually public before reporting success.
    if url and not await _verify_public_url(url):
        return PublishResult(
            False,
            url=url,
            post_id=post_id,
            request_id=request_id,
            error="published to the provider but the public URL could not be verified",
        )
    return PublishResult(
        True,
        url=url,
        post_id=post_id,
        request_id=request_id,
        verified=bool(url),
    )
