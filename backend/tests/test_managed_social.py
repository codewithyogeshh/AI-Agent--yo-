"""One-click connect: the API key must be validated and encrypted, the hosted
connect link must be built from the provider contract, and provider failures
must surface as readable errors rather than 500s.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.db import SessionLocal
from app.models import AuditLog, ContentItem, Secret, User
from app.services import managed_social
from app.tools.base import ToolContext

KEY = "up_live_test_key_123456"


def _make_handler(requests, responses):
    def handle(request: httpx.Request) -> httpx.Response:
        body = {}
        if request.content:
            try:
                body = json.loads(request.content)
            except Exception:  # noqa: BLE001 - non-JSON bodies are still recorded
                body = {}
        requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "body": body,
                "content": request.content,
                "headers": dict(request.headers),
            }
        )
        for (method, suffix), response in responses:
            if request.method == method and request.url.path.endswith(suffix):
                return response
        return httpx.Response(404, json={"success": False, "error_code": "NOT_FOUND"})

    return handle


@pytest.fixture
def provider(monkeypatch):
    requests = []
    responses = []
    managed_social._link_cache.clear()
    managed_social._quota_cache.clear()
    monkeypatch.setattr(managed_social, "transport", httpx.MockTransport(_make_handler(requests, responses)))
    return requests, responses


def _clear_key(user_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(Secret).filter(
            Secret.user_id == user_id, Secret.name == managed_social.KEY_SECRET
        ).delete()
        db.commit()
    finally:
        db.close()


def test_status_without_a_key_is_honest(client, headers, auth, provider):
    _clear_key(auth["user"]["id"])
    data = client.get("/api/integrations/managed", headers=headers).json()
    assert data["configured"] is False
    assert data["connections"] == {}
    assert data["error"] == ""


def test_saving_a_key_validates_and_encrypts_it(client, headers, auth, provider):
    requests, responses = provider
    responses.append(
        (("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []}))
    )
    response = client.post("/api/integrations/managed/key", headers=headers, json={"api_key": KEY})
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is True

    db = SessionLocal()
    try:
        row = (
            db.query(Secret)
            .filter(Secret.user_id == auth["user"]["id"], Secret.name == managed_social.KEY_SECRET)
            .first()
        )
        assert row is not None and row.ciphertext != KEY  # encrypted at rest
        assert (
            db.query(AuditLog)
            .filter(AuditLog.action == "integration.managed_key_saved")
            .count()
            >= 1
        )
    finally:
        db.close()
    assert any(item["path"].endswith("/uploadposts/users") for item in requests)


def test_long_provider_key_is_accepted(client, headers, auth, provider):
    """Real Upload-Post keys are long signed tokens; a short max_length used to
    reject them with an unreadable 422 before the provider was ever asked."""
    _, responses = provider
    responses.append(
        (("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []}))
    )
    long_key = "up_live_" + "k" * 600
    response = client.post("/api/integrations/managed/key", headers=headers, json={"api_key": long_key})
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is True


def test_rejected_key_is_not_stored(client, headers, auth, provider):
    _, responses = provider
    responses.append(
        (("GET", "/uploadposts/users"), httpx.Response(401, json={"success": False}))
    )
    response = client.post("/api/integrations/managed/key", headers=headers, json={"api_key": "bad_key_000000"})
    assert response.status_code == 400
    assert "rejected" in response.json()["detail"].lower()


def test_connect_creates_the_profile_and_returns_the_hosted_page(client, headers, auth, provider):
    requests, responses = provider
    username = auth["user"]["id"]
    responses.extend(
        [
            (("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []})),
            (
                ("POST", "/uploadposts/users"),
                httpx.Response(201, json={"success": True, "profile": {"username": username, "social_accounts": {}}}),
            ),
            (
                ("POST", "/uploadposts/users/generate-jwt"),
                httpx.Response(
                    200,
                    json={"success": True, "access_url": "https://app.upload-post.com/connect?token=abc", "duration": "48h"},
                ),
            ),
        ]
    )

    response = client.post(
        "/api/integrations/managed/connect", headers=headers, json={"platforms": ["youtube"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["url"].startswith("https://app.upload-post.com/connect?token=")

    created = next(item for item in requests if item["method"] == "POST" and item["path"].endswith("/uploadposts/users"))
    assert created["body"]["username"] == username

    jwt = next(item for item in requests if item["path"].endswith("/generate-jwt"))
    assert jwt["body"]["username"] == username
    assert jwt["body"]["platforms"] == ["youtube"]
    assert jwt["body"]["redirect_url"].endswith("/integrations?managed=connected")
    assert jwt["body"]["show_calendar"] is False


def test_status_reports_linked_accounts(client, headers, auth, provider):
    _, responses = provider
    username = auth["user"]["id"]
    responses.append(
        (
            ("GET", "/uploadposts/users"),
            httpx.Response(
                200,
                json={
                    "success": True,
                    "profiles": [
                        {
                            "username": username,
                            "social_accounts": {
                                "youtube": {"handle": "@nova", "display_name": "NOVA"},
                                "instagram": None,
                            },
                        }
                    ],
                },
            ),
        )
    )
    data = client.get("/api/integrations/managed", headers=headers).json()
    platforms = {item["id"]: item for item in data["platforms"]}
    assert platforms["youtube"]["connected"] is True
    assert platforms["youtube"]["handle"] == "@nova"
    assert platforms["instagram"]["connected"] is False


def test_disconnect_unlinks_only_that_platform(client, headers, auth, provider):
    requests, responses = provider
    responses.append(
        (("DELETE", "/uploadposts/users/social"), httpx.Response(200, json={"success": True, "message": "ok"}))
    )
    response = client.post(
                    "/api/integrations/managed/accounts/disconnect", headers=headers, json={"platform": "youtube"}
    )
    assert response.status_code == 200
    call = next(item for item in requests if item["method"] == "DELETE")
    assert call["body"] == {"profile_username": auth["user"]["id"], "social_platform": "youtube"}


def test_plan_limit_from_the_provider_is_reported_clearly(client, headers, auth, provider):
    _, responses = provider
    username = auth["user"]["id"]
    responses.extend(
        [
            (
                ("GET", "/uploadposts/users"),
                httpx.Response(200, json={"success": True, "profiles": [{"username": username}]}),
            ),
            (
                ("POST", "/uploadposts/users/generate-jwt"),
                httpx.Response(402, json={"success": False, "error_code": "PROFILE_LIMIT"}),
            ),
        ]
    )
    response = client.post("/api/integrations/managed/connect", headers=headers, json={"platforms": ["instagram"]})
    assert response.status_code == 400
    assert "PROFILE_LIMIT" in response.json()["detail"]


def test_unsupported_platform_is_refused(client, headers, auth, provider):
    response = client.post("/api/integrations/managed/connect", headers=headers, json={"platforms": ["tiktok"]})
    assert response.status_code == 400
    assert "youtube" in response.json()["detail"].lower()


def _video(tmp_path) -> Path:
    path = tmp_path / "final.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"nova" * 5000)
    return path


def _content_item(video: Path, platform: str = "youtube") -> str:
    db = SessionLocal()
    try:
        user = db.query(User).first()
        item = ContentItem(
            user_id=user.id,
            platform=platform,
            title="Managed publish test",
            caption="A calm test caption",
            asset_path=str(video),
            status="rendered",
        )
        db.add(item)
        db.commit()
        return item.id
    finally:
        db.close()


def _linked_profile(auth, platforms=("youtube",)):
    accounts = {name: {"handle": f"@{name}", "display_name": name.title()} for name in platforms}
    accounts.setdefault("instagram", None)
    return httpx.Response(
        200,
        json={"success": True, "profiles": [{"username": auth["user"]["id"], "social_accounts": accounts}]},
    )


def test_publish_video_sends_the_documented_multipart_request(tmp_path, provider, auth):
    requests, responses = provider
    responses.extend(
        [
            (
                ("POST", "/upload"),
                httpx.Response(
                    200,
                    json={
                        "success": True,
                        "results": {"youtube": {"success": True, "url": "https://youtu.be/abc", "video_id": "abc"}},
                    },
                ),
            ),
            (("GET", "/abc"), httpx.Response(200)),
        ]
    )
    video = _video(tmp_path)
    db = SessionLocal()
    try:
        user = db.query(User).first()
        outcome = asyncio.run(
            managed_social.publish_video(
                db,
                user,
                str(video),
                "youtube",
                title="Title here",
                description="Description",
                tags=["tag"],
                external_id="c_123",
                idempotency_key="nova-c_123-youtube",
                privacy="private",
            )
        )
    finally:
        db.close()

    assert outcome.ok is True
    assert outcome.url == "https://youtu.be/abc"
    assert outcome.post_id == "abc"
    assert outcome.queued is False
    upload = next(item for item in requests if item["path"].endswith("/api/upload"))
    content = upload["content"]
    assert b'name="platform[]"' in content and b"youtube" in content
    assert b'name="user"' in content
    assert b'name="title"' in content and b"Title here" in content
    assert b'name="video"' in content and b"final.mp4" in content
    assert b'name="tags[]"' in content
    assert b'name="privacyStatus"' in content and b"private" in content
    assert upload["headers"].get("idempotency-key") == "nova-c_123-youtube"


def test_publish_video_refuses_an_invalid_privacy_value(tmp_path, provider, auth):
    requests, _ = provider
    db = SessionLocal()
    try:
        user = db.query(User).first()
        with pytest.raises(managed_social.ManagedSocialError) as excinfo:
            asyncio.run(
                managed_social.publish_video(
                    db, user, str(_video(tmp_path)), "youtube", title="Title", privacy="secret"
                )
            )
        assert "privacy" in str(excinfo.value).lower()
    finally:
        db.close()
    assert requests == []  # refused before anything was sent


def test_youtube_tool_forwards_privacy_to_the_managed_upload(tmp_path, provider, auth):
    requests, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), _linked_profile(auth)),
            (
                ("POST", "/upload"),
                httpx.Response(
                    200,
                    json={"success": True, "results": {"youtube": {"success": True, "url": "https://youtu.be/priv", "video_id": "priv"}}},
                ),
            ),
            (("GET", "/priv"), httpx.Response(200)),
        ]
    )
    from app.tools.youtube import youtube_upload

    content_id = _content_item(_video(tmp_path), "youtube")
    db = SessionLocal()
    try:
        user = db.query(User).first()
        ctx = ToolContext(db=db, user=user, task=None, emit=lambda *args, **kwargs: None)
        result = asyncio.run(
            youtube_upload(
                ctx, content_id=content_id, privacy="unlisted", publish_at="2027-01-01T09:00:00Z"
            )
        )
        assert result.ok, result.summary
        assert "unlisted" in result.summary
    finally:
        db.close()

    upload = next(step for step in requests if step["path"].endswith("/api/upload"))
    assert b'name="privacyStatus"' in upload["content"]
    assert b"unlisted" in upload["content"]
    assert b'name="youtube_publish_at"' in upload["content"]
    assert b"2027-01-01T09:00:00Z" in upload["content"]


def test_youtube_tool_uses_the_managed_connection(tmp_path, provider, auth):
    requests, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), _linked_profile(auth)),
            (
                ("POST", "/upload"),
                httpx.Response(
                    200,
                    json={"success": True, "results": {"youtube": {"success": True, "url": "https://youtu.be/xyz", "video_id": "xyz"}}},
                ),
            ),
            (("GET", "/xyz"), httpx.Response(200)),
        ]
    )
    from app.tools.youtube import youtube_upload

    video = _video(tmp_path)
    content_id = _content_item(video, "youtube")
    db = SessionLocal()
    try:
        user = db.query(User).first()
        ctx = ToolContext(db=db, user=user, task=None, emit=lambda *args, **kwargs: None)
        result = asyncio.run(youtube_upload(ctx, content_id=content_id))
        item = db.get(ContentItem, content_id)
        assert result.ok, result.summary
        assert "managed" in result.summary.lower()
        assert item.status == "published"
        assert any(step["path"].endswith("/api/upload") for step in requests)
    finally:
        db.close()


def test_instagram_tool_uses_managed_without_a_public_url(tmp_path, provider, auth):
    requests, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), _linked_profile(auth, ("instagram",))),
            (
                ("POST", "/upload"),
                httpx.Response(
                    200,
                    json={"success": True, "results": {"instagram": {"success": True, "url": "https://instagram.com/p/xyz"}}},
                ),
            ),
            (("GET", "/xyz"), httpx.Response(200)),
        ]
    )
    from app.tools.instagram import instagram_publish

    content_id = _content_item(_video(tmp_path), "instagram")
    db = SessionLocal()
    try:
        user = db.query(User).first()
        ctx = ToolContext(db=db, user=user, task=None, emit=lambda *args, **kwargs: None)
        result = asyncio.run(instagram_publish(ctx, content_id=content_id, caption="Ship it"))
        assert result.ok, result.summary
        assert "managed" in result.summary.lower()
        upload = next(step for step in requests if step["path"].endswith("/api/upload"))
        assert b"Ship it" in upload["content"]
        assert b"privacyStatus" not in upload["content"]  # Instagram has no such field
    finally:
        db.close()


def test_youtube_tool_still_reports_setup_when_nothing_is_linked(tmp_path, provider, auth):
    _, responses = provider
    responses.append((("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []})))
    from app.tools.youtube import youtube_upload

    content_id = _content_item(_video(tmp_path), "youtube")
    db = SessionLocal()
    try:
        user = db.query(User).first()
        ctx = ToolContext(db=db, user=user, task=None, emit=lambda *args, **kwargs: None)
        result = asyncio.run(youtube_upload(ctx, content_id=content_id))
        assert result.ok is False
        assert result.setup_required == "youtube"
    finally:
        db.close()


def _cache_quota(user, count: int, limit: int, reset: str = "") -> None:
    managed_social._quota_cache[user.id] = (
        time.monotonic(),
        managed_social._quota_from(
            {"plan": "Free", "api_usage": {"count": count, "limit": limit, "last_reset": reset}}
        ),
    )


def test_publish_refuses_before_upload_when_cached_quota_is_used_up(tmp_path, provider, auth):
    requests, _ = provider
    db = SessionLocal()
    try:
        user = db.query(User).first()
        _cache_quota(user, 10, 10, reset="2026-12-01T00:00:00Z")
        with pytest.raises(managed_social.ManagedSocialError) as err:
            asyncio.run(managed_social.publish_video(db, user, str(_video(tmp_path)), "youtube", title="T"))
        message = str(err.value)
    finally:
        db.close()
    assert "allowance is used up" in message
    assert "Nothing was uploaded" in message
    assert "2026-12-01T00:00:00Z" in message
    assert requests == [], "no request should be sent once the allowance is known to be gone"


def test_stale_exhausted_quota_does_not_block_publishing_forever(tmp_path, provider, auth):
    _, responses = provider
    responses.extend(
        [
            (("POST", "/upload"), httpx.Response(200, json={"success": True, "results": {"youtube": {"success": True, "url": "https://youtu.be/new", "video_id": "new"}}})),
            (("GET", "/new"), httpx.Response(200)),
        ]
    )
    db = SessionLocal()
    try:
        user = db.query(User).first()
        managed_social._quota_cache[user.id] = (
            0.0,  # older than the TTL, e.g. from before the monthly reset
            managed_social._quota_from({"api_usage": {"count": 10, "limit": 10}}),
        )
        outcome = asyncio.run(managed_social.publish_video(db, user, str(_video(tmp_path)), "youtube", title="T"))
    finally:
        db.close()
    assert outcome.ok is True


def test_publish_still_proceeds_with_the_last_slot(tmp_path, provider, auth):
    requests, responses = provider
    responses.extend(
        [
            (("POST", "/upload"), httpx.Response(200, json={"success": True, "results": {"youtube": {"success": True, "url": "https://youtu.be/last", "video_id": "last"}}})),
            (("GET", "/last"), httpx.Response(200)),
        ]
    )
    db = SessionLocal()
    try:
        user = db.query(User).first()
        _cache_quota(user, 9, 10)
        outcome = asyncio.run(managed_social.publish_video(db, user, str(_video(tmp_path)), "youtube", title="T"))
    finally:
        db.close()
    assert outcome.ok is True
    assert any(item["path"].endswith("/upload") for item in requests)


def test_publish_proceeds_when_quota_is_unknown(tmp_path, provider, auth):
    _, responses = provider
    responses.extend(
        [
            (("POST", "/upload"), httpx.Response(200, json={"success": True, "results": {"youtube": {"success": True, "url": "https://youtu.be/x", "video_id": "x"}}})),
            (("GET", "/x"), httpx.Response(200)),
        ]
    )
    db = SessionLocal()
    try:
        user = db.query(User).first()
        managed_social._quota_cache[user.id] = (
            time.monotonic(),
            {**managed_social._empty_quota(), "error": "usage unavailable"},
        )
        outcome = asyncio.run(managed_social.publish_video(db, user, str(_video(tmp_path)), "youtube", title="T"))
    finally:
        db.close()
    assert outcome.ok is True


def test_publish_surfaces_the_429_race_instead_of_double_checking(tmp_path, provider, auth):
    requests, responses = provider
    responses.append(
        (
            ("POST", "/upload"),
            httpx.Response(
                429,
                json={"success": False, "message": "This upload would exceed your monthly limit.", "usage": {"count": 10, "limit": 10}},
            ),
        )
    )
    db = SessionLocal()
    try:
        user = db.query(User).first()
        # Cache says one slot is left, but the provider took it first.
        _cache_quota(user, 9, 10)
        with pytest.raises(managed_social.ManagedSocialError) as err:
            asyncio.run(managed_social.publish_video(db, user, str(_video(tmp_path)), "youtube", title="T"))
        message = str(err.value)
    finally:
        db.close()
    assert "monthly limit reached" in message
    assert "(used 10 of 10)" in message
    assert any(item["path"].endswith("/upload") for item in requests)


def test_quota_warning_notifies_only_on_level_transitions(auth):
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).first()
        managed_social._quota_cache.clear()
        managed_social._quota_notified.clear()
        payloads = [
            {"plan": "Free", "api_usage": {"count": 8, "limit": 10, "last_reset": "2026-12-01T00:00:00Z"}},
            {"plan": "Free", "api_usage": {"count": 8, "limit": 10, "last_reset": "2026-12-01T00:00:00Z"}},
            {"plan": "Free", "api_usage": {"count": 10, "limit": 10, "last_reset": "2026-12-01T00:00:00Z"}},
            {"plan": "Free", "api_usage": {"count": 3, "limit": 10, "last_reset": "2026-12-01T00:00:00Z"}},
            {"plan": "Free", "api_usage": {"count": 8, "limit": 10, "last_reset": "2026-12-01T00:00:00Z"}},
        ]

        async def fake_call(method, path, key, payload=None):
            return payloads.pop(0)

        with patch("app.services.notifications.notify_user", new_callable=AsyncMock) as notify, \
             patch.object(managed_social, "_call", fake_call), \
             patch.object(managed_social, "api_key", lambda db, user: KEY):
            r1 = asyncio.run(managed_social.quota(db, user, fresh=True))
            r2 = asyncio.run(managed_social.quota(db, user, fresh=True))
            r3 = asyncio.run(managed_social.quota(db, user, fresh=True))
            r4 = asyncio.run(managed_social.quota(db, user, fresh=True))
            r5 = asyncio.run(managed_social.quota(db, user, fresh=True))

        assert r1["level"] == "low" and r2["level"] == "low"
        assert r3["level"] == "exhausted"
        assert r4["level"] == "ok"
        assert r5["level"] == "low"
        # Only the three upward transitions notify: low, exhausted, low again.
        assert notify.await_count == 3
        assert notify.await_args_list[0].kwargs["level"] == "warn"
        assert notify.await_args_list[2].kwargs["level"] == "warn"
        assert notify.await_args_list[1].kwargs["level"] == "error"
        # The in-memory marker is what suppresses the repeated low reading.
        assert managed_social._quota_notified[user.id] == "low"
    finally:
        db.close()


def test_quota_marker_blocks_repeated_whatsapp_messages(auth):
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).first()
        managed_social._quota_cache.clear()
        managed_social._quota_notified.clear()
        managed_social._quota_notified[user.id] = "low"  # already warned

        async def fake_call(method, path, key, payload=None):
            return {"plan": "Free", "api_usage": {"count": 9, "limit": 10, "last_reset": "2026-12-01T00:00:00Z"}}

        with patch("app.services.notifications.notify_user", new_callable=AsyncMock) as notify, \
             patch.object(managed_social, "_call", fake_call), \
             patch.object(managed_social, "api_key", lambda db, user: KEY):
            result = asyncio.run(managed_social.quota(db, user, fresh=True))

        assert result["level"] == "low"
        assert notify.await_count == 0
    finally:
        db.close()


def test_publish_via_managed_notifies_on_managed_social_error(tmp_path, provider, auth):
    requests, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), _linked_profile(auth)),
            (("POST", "/upload"), httpx.Response(400, json={"success": False, "error_code": "BAD_MEDIA"})),
        ]
    )
    from app.tools.youtube import youtube_upload

    content_id = _content_item(_video(tmp_path), "youtube")
    db = SessionLocal() if False else None
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).first()
        ctx = ToolContext(db=db, user=user, task=None, emit=lambda *a, **k: None)
        with patch("app.services.notifications.notify_user", new_callable=AsyncMock) as notify:
            result = asyncio.run(youtube_upload(ctx, content_id=content_id))
    finally:
        db.close()

    assert result.ok is False
    assert "YouTube publishing failed" in result.summary
    assert result.verified is False
    assert notify.await_count == 1
    assert notify.await_args.args[2] == "YouTube publish failed"
    assert "BAD_MEDIA" in notify.await_args.args[3] or "error 400" in notify.await_args.args[3].lower()


def test_publish_via_managed_notifies_on_provider_reported_failure(tmp_path, provider, auth):
    requests, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), _linked_profile(auth)),
            (
                ("POST", "/upload"),
                httpx.Response(200, json={"success": True, "results": {"youtube": {"success": False, "error": "session expired"}}}),
            ),
        ]
    )
    from app.tools.youtube import youtube_upload
    from app.db import SessionLocal

    content_id = _content_item(_video(tmp_path), "youtube")
    db = SessionLocal()
    try:
        user = db.query(User).first()
        ctx = ToolContext(db=db, user=user, task=None, emit=lambda *a, **k: None)
        with patch("app.services.notifications.notify_user", new_callable=AsyncMock) as notify:
            result = asyncio.run(youtube_upload(ctx, content_id=content_id))
    finally:
        db.close()

    assert result.ok is False
    assert "YouTube publishing failed" in result.summary
    assert "session expired" in result.summary
    assert result.verified is False
    assert notify.await_count == 1
    assert notify.await_args.args[2] == "YouTube publish failed"
    assert "session expired" in notify.await_args.args[3]


def _me(count, limit, plan="Free", reset="2026-12-01T00:00:00Z"):
    return httpx.Response(
        200, json={"success": True, "plan": plan, "api_usage": {"count": count, "limit": limit, "last_reset": reset}}
    )


def test_quota_shows_usage_and_warns_when_low(client, headers, auth, provider):
    _, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []})),
            (("GET", "/uploadposts/me"), _me(8, 10)),
        ]
    )
    data = client.get("/api/integrations/managed", headers=headers).json()
    quota = data["quota"]
    assert quota["available"] is True
    assert quota["used"] == 8 and quota["limit"] == 10
    assert quota["remaining"] == 2 and quota["percent"] == 80.0
    assert quota["level"] == "low"
    assert quota["plan"] == "Free"
    assert quota["resets_at"] == "2026-12-01T00:00:00Z"


def test_quota_is_exhausted_at_the_limit(client, headers, auth, provider):
    _, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []})),
            (("GET", "/uploadposts/me"), _me(10, 10)),
        ]
    )
    quota = client.get("/api/integrations/managed", headers=headers).json()["quota"]
    assert quota["remaining"] == 0
    assert quota["level"] == "exhausted"
    assert quota["percent"] == 100.0


def test_quota_handles_unlimited_plans(client, headers, auth, provider):
    _, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []})),
            (("GET", "/uploadposts/me"), _me(3, 0, plan="Professional")),
        ]
    )
    quota = client.get("/api/integrations/managed", headers=headers).json()["quota"]
    assert quota["available"] is True
    assert quota["unlimited"] is True
    assert quota["used"] == 3
    assert quota["level"] == "ok"


def test_quota_unavailable_is_reported_not_invented(client, headers, auth, provider):
    _, responses = provider
    responses.extend(
        [
            (("GET", "/uploadposts/users"), httpx.Response(200, json={"success": True, "profiles": []})),
            (("GET", "/uploadposts/me"), httpx.Response(200, json={"success": True, "plan": "Free"})),
        ]
    )
    quota = client.get("/api/integrations/managed", headers=headers).json()["quota"]
    assert quota["available"] is False
    assert quota["used"] is None
    assert "usage" in quota["error"].lower()


def test_dashboard_status_matches_what_the_tools_use(client, headers, auth, provider):
    _, responses = provider
    responses.append((("GET", "/uploadposts/users"), _linked_profile(auth)))

    data = client.get("/api/integrations", headers=headers).json()
    providers = {item["id"]: item for item in data["integrations"]}
    assert providers["youtube"]["status"] == "not_configured"  # no direct Google credentials
    assert providers["youtube"]["effective_status"] == "connected"  # but the tool will use managed
    assert providers["youtube"]["channel"] == "managed"
    assert providers["youtube"]["managed_handle"] == "@youtube"
    assert providers["google"]["channel"] == "none"


def test_connection_test_endpoint_reports_the_managed_link(client, headers, auth, provider):
    _, responses = provider
    responses.append((("GET", "/uploadposts/users"), _linked_profile(auth)))

    result = client.post("/api/integrations/youtube/test", headers=headers).json()
    assert result["ok"] is True
    assert result["channel"] == "managed"
    assert "upload-post" in result["detail"].lower()
