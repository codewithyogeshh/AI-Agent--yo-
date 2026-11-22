"""WhatsApp Cloud API webhook.

Security order: verify signature -> check allowlist -> resolve owner -> act.
Unsigned or unverified traffic is rejected outright.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..agent.orchestrator import acknowledgement, record_chat, submit_task
from ..config import settings
from ..db import SessionLocal, get_db
from ..models import User
from ..security import audit, verify_whatsapp_signature
from ..services import approvals as approval_service
from ..services import whatsapp

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])
logger = logging.getLogger("nova.whatsapp")


@router.get("/webhook")
def verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> PlainTextResponse:
    if not settings.whatsapp_verify_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WHATSAPP_VERIFY_TOKEN is not configured")
    if hub_mode == "subscribe" and hub_token == settings.whatsapp_verify_token:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Verification failed")


@router.post("/webhook")
async def receive(request: Request, background: BackgroundTasks) -> dict:
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    if not settings.whatsapp_app_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WHATSAPP_APP_SECRET is required to verify webhook signatures — refusing unsigned traffic.",
        )
    if not verify_whatsapp_signature(raw, signature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    payload: Dict[str, Any] = await request.json()
    for message in whatsapp.parse_webhook(payload):
        background.add_task(_process, message)
    return {"received": True}


def _resolve_user(db: Session, phone: str) -> Optional[User]:
    normalized = phone.replace(" ", "")
    user = db.query(User).filter(User.phone == normalized).first()
    if user is None:
        user = db.query(User).filter(User.phone == f"+{normalized.lstrip('+')}").first()
    if user is None:
        owners = db.query(User).filter(User.role.in_(["owner", "admin"])).all()
        if len(owners) == 1:
            user = owners[0]
    return user


def _pending_lines(approvals: list, limit: int = 5) -> str:
    lines = [f"• {row.id} — {(row.action or row.tool)[:70]}" for row in approvals[:limit]]
    if len(approvals) > limit:
        lines.append(f"…and {len(approvals) - limit} more")
    return "\n".join(lines)


async def _handle_decision(db: Session, user: User, sender: str, command: approval_service.DecisionCommand) -> None:
    """Apply an approve/reject reply using the same service the dashboard uses."""
    approval, matches = approval_service.find_pending(db, user, command.reference)
    if approval is None:
        if matches:
            message = (
                "Which approval? Reply with the full ID, for example “approve "
                f"{matches[0].id}”.\n\nPending:\n{_pending_lines(matches)}"
            )
        else:
            message = (
                f"No pending approval matches “{command.reference}”. Nothing was changed. "
                "Pending approvals are listed in the dashboard under Tasks → Approvals."
            )
        record_chat(db, user, "assistant", message, source="whatsapp")
        await whatsapp.send_text(sender, message[:3900])
        return

    try:
        updated, task = approval_service.decide(
            db, user, approval, command.action == "approve", command.note, actor="whatsapp"
        )
    except ValueError as exc:
        message = f"{exc}. Nothing was changed."
        record_chat(db, user, "assistant", message, source="whatsapp")
        await whatsapp.send_text(sender, message[:3900])
        return

    if command.action == "approve":
        message = (
            f"✅ Approved {updated.id}.\n{updated.action[:140]}\n"
            f"Task re-queued: {task.title if task else '—'}\nI will report when it finishes."
        )
    else:
        message = (
            f"❌ Rejected {updated.id}.\n{updated.action[:140]}\n"
            f"Task cancelled: {task.title if task else '—'}"
        )
    record_chat(db, user, "user", f"{command.action} {updated.id}", source="whatsapp")
    record_chat(db, user, "assistant", message, source="whatsapp")
    await whatsapp.send_text(sender, message[:3900])


async def _process(message: Dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        sender = message.get("from", "")
        if not whatsapp.is_allowed(sender):
            logger.warning("Rejected WhatsApp message from non-allowlisted number")
            return
        if not whatsapp.configured():
            logger.error("WhatsApp inbound received but outbound is not configured")
            return
        user = _resolve_user(db, sender)
        if user is None:
            await whatsapp.send_text(
                sender,
                "This number is allowlisted but no NOVA account is linked to it. "
                "Sign in to the dashboard and save this phone number in settings.",
            )
            return

        text = message.get("text", "") or ""
        if message["type"] in {"audio", "voice"} and message.get("media_id"):
            audio = await whatsapp.download_media(message["media_id"])
            transcript = await whatsapp.transcribe_audio(audio, message.get("mime", "audio/ogg"))
            if not transcript:
                await whatsapp.send_text(
                    sender,
                    "Voice notes need a transcription provider. Add OPENAI_API_KEY or GEMINI_API_KEY, "
                    "or send the instruction as text.",
                )
                audit(db, user.id, "whatsapp.voice_unavailable", sender, level="warning")
                return
            text = transcript
        elif message["type"] in {"image", "document"} and message.get("media_id"):
            media_bytes = await whatsapp.download_media(message["media_id"])
            folder = settings.workspace_dir / user.id / "inbox"
            folder.mkdir(parents=True, exist_ok=True)
            name = message.get("filename") or f"{message['type']}-{message['id'][:8]}"
            path = folder / name
            path.write_bytes(media_bytes)
            note = message.get("text") or "Please review this attachment."
            text = f"{note}\n\n(Attachment saved at inbox/{name})"

        button_id = message.get("button_id") or ""
        if button_id:
            command = approval_service.parse_button_id(button_id)
            if command is None:
                await whatsapp.send_text(
                    sender,
                    "That button is not recognised. Reply “approve <id>” or “reject <id>”, "
                    "or decide in the dashboard under Tasks → Approvals.",
                )
                return
            await _handle_decision(db, user, sender, command)
            return

        if not text.strip():
            await whatsapp.send_text(sender, "I received that but could not read an instruction from it.")
            return

        decision = approval_service.parse_decision(text)
        if decision is not None:
            await _handle_decision(db, user, sender, decision)
            return

        record_chat(db, user, "user", text, source="whatsapp")
        try:
            task = await submit_task(db, user, text, source="whatsapp")
        except ValueError as exc:
            await whatsapp.send_text(sender, str(exc))
            return
        reply = acknowledgement(task)
        record_chat(db, user, "assistant", reply, task_id=task.id, source="whatsapp")
        await whatsapp.send_text(sender, reply[:3900])
        audit(db, user.id, "whatsapp.inbound", task.id, data={"type": message["type"]}, actor="whatsapp")
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp message processing failed")
    finally:
        db.close()
