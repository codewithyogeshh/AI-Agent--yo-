"""Multi-channel notifications. Dashboard is always written; WhatsApp is optional."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Notification, User
from . import whatsapp

logger = logging.getLogger("nova.notifications")


async def notify_user(
    db: Session,
    user: User,
    title: str,
    body: str,
    level: str = "info",
    meta: Dict[str, Any] | None = None,
    buttons: Optional[List[Dict[str, str]]] = None,
) -> List[str]:
    """Write the dashboard notification and push to WhatsApp when allowed.

    `buttons` sends an interactive reply-button message; if the push fails (for
    example the 24-hour service window is closed) the same body is resent as
    text so the notification is never lost.
    """
    channels = ["dashboard"]
    db.add(
        Notification(
            user_id=user.id,
            channel="dashboard",
            title=title[:300],
            body=body,
            level=level,
            meta_json=json.dumps(meta or {}, default=str),
        )
    )
    db.commit()
    if whatsapp.configured() and user.phone and whatsapp.is_allowed(user.phone):
        delivered = False
        if buttons:
            try:
                await whatsapp.send_buttons(user.phone, f"*{title}*\n\n{body}"[:1024], buttons)
                delivered = True
            except Exception as exc:  # noqa: BLE001 - fall back to text, never fail the task
                logger.warning("Interactive WhatsApp send failed, falling back to text: %s", exc)
        if not delivered:
            try:
                await whatsapp.send_text(user.phone, f"*{title}*\n\n{body}"[:3900])
                delivered = True
            except Exception:
                # A failed push must never break the task result.
                pass
        if delivered:
            channels.append("whatsapp")
    return channels
