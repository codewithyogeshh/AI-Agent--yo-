"""Event triggers: signed inbound webhooks that become ordinary NOVA tasks.

A trigger is just a saved prompt template plus a secret. Inbound events are
verified, filtered, interpolated into the template and handed to the normal
orchestrator — so planning, permissions, approvals, verification and audit all
behave exactly as they do for a typed instruction.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

from ..security import decrypt_value, encrypt_value

MAX_BODY_BYTES = 64 * 1024
RATE_LIMIT = 30  # events per trigger ...
RATE_WINDOW_SECONDS = 60  # ... in this window

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.\[\]-]+)\s*\}\}")


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def seal(secret: str) -> str:
    """Encrypt the HMAC secret at rest with the app key."""
    return encrypt_value(secret)


def unseal(blob: str) -> str:
    return decrypt_value(blob)


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def signature_valid(secret: str, body: bytes, provided: str) -> bool:
    return hmac.compare_digest(signature(secret, body), (provided or "").strip())


def _lookup(payload: Any, path: str) -> Any:
    """Resolve `a.b.0.c` against a JSON object. Missing values become ""."""
    if path in {"payload", "event"}:
        return payload
    current: Any = payload
    for part in path.replace("[", ".").replace("]", "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
        if current is None:
            return ""
    return current


def render_prompt(template: str, payload: Dict[str, Any]) -> str:
    """Fill `{{placeholders}}`; templates without any get the payload appended."""

    def replace(match: re.Match[str]) -> str:
        value = _lookup(payload, match.group(1))
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        if isinstance(value, bool):
            return "true" if value else "false"
        return "" if value is None else str(value)

    rendered = PLACEHOLDER_RE.sub(replace, template).strip()
    if not PLACEHOLDER_RE.search(template):
        rendered += "\n\nEvent payload:\n" + json.dumps(payload, ensure_ascii=False, default=str)[:4000]
    return rendered[:8000]


def parse_filters(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def matches(filters: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    """Every configured filter must match the event exactly (string-compared)."""
    for path, expected in filters.items():
        actual = _lookup(payload, path)
        if isinstance(expected, bool):
            if bool(actual) is not expected:
                return False
        elif isinstance(expected, (int, float)):
            if actual != expected:
                return False
        elif str(actual) != str(expected):
            return False
    return True


_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def rate_limited(trigger_id: str) -> bool:
    """Simple in-process limiter: a runaway sender cannot flood the task queue."""
    now = time.monotonic()
    bucket = _buckets[trigger_id]
    while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT:
        return True
    bucket.append(now)
    return False


def reset_rate_limits() -> None:
    _buckets.clear()
