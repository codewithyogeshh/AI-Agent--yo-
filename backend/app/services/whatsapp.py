"""WhatsApp Cloud API client.

Official Graph API only. Incoming webhooks are signature-verified before the
payload is trusted; only allowlisted numbers can control NOVA.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from ..config import settings

GRAPH_URL = "https://graph.facebook.com/v21.0"


def configured() -> bool:
    return bool(settings.whatsapp_token and settings.whatsapp_phone_number_id)


def is_allowed(number: str) -> bool:
    normalized = (number or "").replace(" ", "").replace("-", "")
    if not normalized.startswith("+"):
        normalized = "+" + normalized.lstrip("+")
    return normalized in settings.whatsapp_allowed


async def send_text(to: str, body: str) -> Dict[str, Any]:
    if not configured():
        raise RuntimeError("WhatsApp is not configured (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID)")
    payload = {
        "messaging_product": "whatsapp",
        "to": to.replace(" ", ""),
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}", "Content-Type": "application/json"},
            json=payload,
        )
        if res.status_code >= 400:
            raise RuntimeError(f"WhatsApp send failed {res.status_code}: {res.text[:300]}")
        return res.json()


def button_payload(to: str, body: str, buttons: List[Dict[str, str]], footer: str = "") -> Dict[str, Any]:
    """Build a Cloud API interactive reply-button message.

    Cloud API rules enforced here: at most 3 buttons, body <= 1024 chars,
    button title <= 20 chars. Button ids return as `interactive.button_reply.id`.
    """
    prepared = [
        {"type": "reply", "reply": {"id": str(b.get("id", ""))[:256], "title": str(b.get("title", ""))[:20]}}
        for b in buttons[:3]
        if b.get("id")
    ]
    if not prepared:
        raise ValueError("Interactive message needs at least one button with an id")
    interactive: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body[:1024]},
        "action": {"buttons": prepared},
    }
    if footer:
        interactive["footer"] = {"text": footer[:60]}
    return {
        "messaging_product": "whatsapp",
        "to": to.replace(" ", ""),
        "type": "interactive",
        "interactive": interactive,
    }


async def send_buttons(
    to: str, body: str, buttons: List[Dict[str, str]], footer: str = ""
) -> Dict[str, Any]:
    """Send an interactive reply-button message (see `button_payload` for limits)."""
    if not configured():
        raise RuntimeError("WhatsApp is not configured (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID)")
    payload = button_payload(to, body, buttons, footer)
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}", "Content-Type": "application/json"},
            json=payload,
        )
        if res.status_code >= 400:
            raise RuntimeError(f"WhatsApp send failed {res.status_code}: {res.text[:300]}")
        return res.json()


async def send_document(to: str, link: str, filename: str, caption: str = "") -> Dict[str, Any]:
    if not configured():
        raise RuntimeError("WhatsApp is not configured")
    payload = {
        "messaging_product": "whatsapp",
        "to": to.replace(" ", ""),
        "type": "document",
        "document": {"link": link, "filename": filename, "caption": caption[:900]},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{GRAPH_URL}/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}", "Content-Type": "application/json"},
            json=payload,
        )
        if res.status_code >= 400:
            raise RuntimeError(f"WhatsApp send failed {res.status_code}: {res.text[:300]}")
        return res.json()


async def media_url(media_id: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            f"{GRAPH_URL}/{media_id}",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        )
        res.raise_for_status()
        return res.json().get("url", "")


async def download_media(media_id: str) -> bytes:
    url = await media_url(media_id)
    if not url:
        raise RuntimeError("Could not resolve WhatsApp media URL")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        res = await client.get(url, headers={"Authorization": f"Bearer {settings.whatsapp_token}"})
        res.raise_for_status()
        return res.content


async def transcribe_audio(data: bytes, mime: str = "audio/ogg") -> Optional[str]:
    """Voice notes need a transcription provider. Returns None when unavailable
    so the caller can tell the user exactly what to configure."""
    if settings.openai_api_key:
        async with httpx.AsyncClient(timeout=90) as client:
            res = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                files={"file": ("voice.ogg", data, mime)},
                data={"model": "whisper-1"},
            )
            if res.status_code < 400:
                return res.json().get("text", "")
    if settings.gemini_api_key:
        import base64

        async with httpx.AsyncClient(timeout=90) as client:
            res = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
                f"?key={settings.gemini_api_key}",
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": "Transcribe this audio verbatim. Return only the transcript."},
                                {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}},
                            ]
                        }
                    ]
                },
            )
            if res.status_code < 400:
                data_json = res.json()
                parts = data_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts).strip()
    return None


def parse_webhook(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalise Cloud API webhook payloads into simple inbound messages."""
    parsed: List[Dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for message in value.get("messages", []):
                item: Dict[str, Any] = {
                    "from": message.get("from", ""),
                    "name": contacts.get(message.get("from", ""), ""),
                    "id": message.get("id", ""),
                    "type": message.get("type", "text"),
                    "timestamp": message.get("timestamp", ""),
                    "text": "",
                    "button_id": "",
                    "media_id": "",
                    "mime": "",
                    "filename": "",
                }
                if item["type"] == "text":
                    item["text"] = message.get("text", {}).get("body", "")
                elif item["type"] in {"audio", "voice"}:
                    item["media_id"] = message.get("audio", {}).get("id", "")
                    item["mime"] = message.get("audio", {}).get("mime_type", "audio/ogg")
                elif item["type"] == "image":
                    item["media_id"] = message.get("image", {}).get("id", "")
                    item["mime"] = message.get("image", {}).get("mime_type", "image/jpeg")
                    item["text"] = message.get("image", {}).get("caption", "")
                elif item["type"] == "document":
                    item["media_id"] = message.get("document", {}).get("id", "")
                    item["mime"] = message.get("document", {}).get("mime_type", "")
                    item["filename"] = message.get("document", {}).get("filename", "")
                    item["text"] = message.get("document", {}).get("caption", "")
                elif item["type"] == "button":
                    item["text"] = message.get("button", {}).get("text", "")
                elif item["type"] == "interactive":
                    interactive = message.get("interactive", {})
                    reply = interactive.get(interactive.get("type", "button_reply"), {})
                    item["button_id"] = reply.get("id", "")
                    item["text"] = reply.get("title", "")
                parsed.append(item)
    return parsed
