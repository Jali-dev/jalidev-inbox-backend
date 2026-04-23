"""
Telegram webhook router for JaliDev Inbox.
Receives updates from Telegram Bot API and processes inbound messages.

Setup:
  1. Get bot token from @BotFather
  2. Set TELEGRAM_BOT_TOKEN in .env
  3. Register webhook: POST https://api.telegram.org/bot{TOKEN}/setWebhook
     with {"url": "https://api.jalidev.online/api/webhooks/telegram"}
  4. Or call GET /api/webhooks/telegram/setup to register automatically.
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import supabase_service, n8n_service, telegram_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks-telegram"])


# ─────────────────────────────────────────────
# Telegram Update Schemas (minimal, what we need)
# ─────────────────────────────────────────────

class TelegramUser(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    is_bot: bool = False


class TelegramChat(BaseModel):
    id: int
    type: str  # "private", "group", "supergroup", "channel"


class TelegramMessage(BaseModel):
    message_id: int
    from_: TelegramUser | None = Field(None, alias="from")
    chat: TelegramChat
    text: str | None = None
    date: int = 0

    class Config:
        populate_by_name = True


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _build_contact_name(user: TelegramUser) -> str:
    parts = [user.first_name, user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or user.username or f"tg:{user.id}"


def _tg_external_id(user: TelegramUser) -> str:
    """Canonical external_id for Telegram contacts: tg:{user_id}"""
    return f"tg:{user.id}"


# ─────────────────────────────────────────────
# Background task: persist + trigger AI
# ─────────────────────────────────────────────

async def _handle_tg_message(update: TelegramUpdate) -> None:
    msg = update.message
    if not msg or not msg.text or not msg.from_ or msg.from_.is_bot:
        return

    user = msg.from_
    chat_id = str(msg.chat.id)
    external_id = _tg_external_id(user)
    contact_name = _build_contact_name(user)
    text = msg.text.strip()

    # 1. Upsert contact
    contact = await supabase_service.upsert_contact(
        external_id=external_id,
        name=contact_name,
        channel="telegram",
        # phone is not available for Telegram — use chat_id as identifier
        phone=None,
    )

    # 2. Get or create conversation
    conversation = await supabase_service.get_or_create_conversation(
        contact_id=contact["id"],
        channel="telegram",
        external_chat_id=chat_id,
    )

    # 3. Save inbound message
    await supabase_service.save_inbound_message(
        conversation_id=conversation["id"],
        content=text,
        external_message_id=str(msg.message_id),
    )

    # 4. Mark as read (no concept in Telegram bot API for this, skip)

    # 5. Trigger AI if active
    if conversation.get("is_ai_active", True):
        await n8n_service.trigger_ai_workflow(
            conversation_id=conversation["id"],
            contact_name=contact_name,
            message=text,
            channel="telegram",
            # chat_id needed in callback so FastAPI knows where to reply
            extra={"telegram_chat_id": chat_id},
        )


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@router.post(
    "/telegram",
    status_code=status.HTTP_200_OK,
    summary="Telegram Bot webhook receiver",
)
async def receive_telegram_update(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    Telegram calls this endpoint for every incoming update.
    We respond 200 immediately and process in the background.
    """
    try:
        raw = await request.json()
    except Exception:
        # Telegram expects 200 even on parse errors — log and move on
        logger.warning("[telegram] Could not parse update body")
        return {"ok": True}

    try:
        update = TelegramUpdate(**raw)
    except Exception as exc:
        logger.warning(f"[telegram] Could not validate update: {exc}")
        return {"ok": True}

    # Only handle private text messages for now
    from_ = update.message.from_ if update.message else None
    if update.message and update.message.text and from_ and not from_.is_bot:
        background_tasks.add_task(_handle_tg_message, update)

    return {"ok": True}


@router.get(
    "/telegram/setup",
    summary="Register Telegram webhook URL (call once on deploy)",
)
async def setup_telegram_webhook() -> dict[str, Any]:
    """
    Registers this server's URL as the Telegram webhook.
    Requires TELEGRAM_BOT_TOKEN and FASTAPI_BASE_URL in .env.
    """
    webhook_url = f"{settings.FASTAPI_BASE_URL}/api/webhooks/telegram"
    result = await telegram_service.set_webhook(webhook_url)
    return result


@router.get(
    "/telegram/info",
    summary="Get current Telegram webhook info",
)
async def telegram_webhook_info() -> dict[str, Any]:
    return await telegram_service.get_webhook_info()
