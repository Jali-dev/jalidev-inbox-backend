"""
Meta / WhatsApp Cloud API service for JaliDev Inbox.
Handles sending messages via the Meta Graph API.
"""

import httpx
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


async def send_text_message(to: str, text: str) -> bool:
    """
    Send a plain text WhatsApp message via Meta Cloud API.
    `to` should be the recipient's phone number (with country code, no +).
    Returns True on success, False on failure (non-raising).
    """
    if not settings.META_PHONE_NUMBER_ID or not settings.META_ACCESS_TOKEN:
        logger.warning("[meta] META_PHONE_NUMBER_ID or META_ACCESS_TOKEN not configured")
        return False

    url = f"{GRAPH_API_BASE}/{settings.META_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.exception(f"[meta] Failed to send WhatsApp message to {to}: {exc}")
        return False
