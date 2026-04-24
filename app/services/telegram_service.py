"""
Telegram Bot API service for JaliDev Inbox.
Handles sending messages via the Telegram Bot API.
"""

import httpx
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _resolve_token(bot_token: str | None = None) -> str:
    return (bot_token or settings.TELEGRAM_BOT_TOKEN or "").strip()


def _telegram_url(method: str, bot_token: str | None = None) -> str:
    return TELEGRAM_API_BASE.format(token=_resolve_token(bot_token), method=method)


async def send_telegram_message(chat_id: str | int, text: str, bot_token: str | None = None) -> bool:
    """
    Send a plain text message to a Telegram chat.
    Returns True on success, False on failure (non-raising).
    """
    token = _resolve_token(bot_token)
    if not token:
        logger.error("[telegram] Missing bot token for sendMessage")
        return False

    url = _telegram_url("sendMessage", token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"[telegram] sendMessage failed: {data}")
                return False
            return True
    except Exception as exc:
        logger.exception(f"[telegram] Exception in send_telegram_message: {exc}")
        return False


async def set_webhook(webhook_url: str) -> dict:
    """
    Register the webhook URL with Telegram.
    Call this once during setup or on redeploy.
    Returns the Telegram API response.
    """
    url = _telegram_url("setWebhook")
    payload = {
        "url": webhook_url,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


async def get_webhook_info() -> dict:
    """Returns current webhook configuration from Telegram."""
    url = _telegram_url("getWebhookInfo")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
