"""
Messages router — send outbound messages and receive n8n AI callback.

Endpoints:
  POST /api/messages/send          — frontend/agent sends a message
  POST /api/internal/n8n-reply     — n8n AI workflow callback (authenticated)
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.services import supabase_service, meta_service, telegram_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["messages"])


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    conversation_id: str
    text: str


class N8nReplyPayload(BaseModel):
    conversation_id: str
    reply: str
    channel: str  # "telegram" | "whatsapp"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _send_outbound(
    channel: str,
    conversation: dict,
    contact: dict,
    text: str,
) -> bool:
    """
    Route outbound message to the correct channel API.
    Returns True on success.
    """
    if channel == "telegram":
        # external_chat_id stored on conversation, or fall back to contact external_id
        chat_id = conversation.get("external_chat_id") or contact.get("external_id", "").replace("tg:", "")
        if not chat_id:
            logger.error(f"[send] No telegram chat_id for conversation {conversation['id']}")
            return False
        return await telegram_service.send_telegram_message(chat_id=chat_id, text=text)

    elif channel == "whatsapp":
        # Meta / WhatsApp Cloud API — phone number stored in contact.phone
        phone = contact.get("phone") or contact.get("external_id", "")
        if not phone:
            logger.error(f"[send] No phone for WhatsApp conversation {conversation['id']}")
            return False
        return await meta_service.send_text_message(to=phone, text=text)

    else:
        logger.warning(f"[send] Unknown channel '{channel}' for conversation {conversation['id']}")
        return False


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@router.post(
    "/api/messages/send",
    status_code=status.HTTP_200_OK,
    summary="Send outbound message (from agent or frontend)",
)
async def send_message(payload: SendMessageRequest) -> dict[str, Any]:
    """
    Agent or frontend calls this to send a message to the contact.
    Saves to Supabase and routes to the correct channel API.
    """
    # 1. Load conversation + contact
    conv_data = await supabase_service.get_conversation_with_contact(payload.conversation_id)
    if not conv_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    conversation = conv_data["conversation"]
    contact = conv_data["contact"]
    channel = conversation.get("channel", "telegram")

    # 2. Save outbound message to Supabase
    await supabase_service.save_outbound_message(
        conversation_id=payload.conversation_id,
        content=payload.text,
        sender_type="agent",
    )

    # 3. Send via channel
    ok = await _send_outbound(
        channel=channel,
        conversation=conversation,
        contact=contact,
        text=payload.text,
    )

    if not ok:
        logger.error(f"[send] Failed to deliver message for conversation {payload.conversation_id}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Message saved but delivery to channel failed",
        )

    return {"ok": True}


@router.post(
    "/api/internal/n8n-reply",
    status_code=status.HTTP_200_OK,
    summary="n8n AI workflow callback — receives AI-generated reply",
)
async def n8n_ai_reply(
    payload: N8nReplyPayload,
    x_callback_key: str | None = Header(default=None, alias="X-Callback-Key"),
) -> dict[str, Any]:
    """
    n8n WF-06 calls this endpoint after generating an AI reply.
    Authenticates via X-Callback-Key header.
    Saves the reply to Supabase and sends it to the contact.
    """
    # 1. Authenticate
    if x_callback_key != settings.N8N_CALLBACK_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid callback key",
        )

    # 2. Load conversation + contact
    conv_data = await supabase_service.get_conversation_with_contact(payload.conversation_id)
    if not conv_data:
        logger.error(f"[n8n-reply] Conversation not found: {payload.conversation_id}")
        return {"ok": False, "error": "conversation_not_found"}

    conversation = conv_data["conversation"]
    contact = conv_data["contact"]
    channel = payload.channel or conversation.get("channel", "telegram")

    # 3. Save AI reply to Supabase
    await supabase_service.save_outbound_message(
        conversation_id=payload.conversation_id,
        content=payload.reply,
        sender_type="bot",
    )

    # 4. Send via channel
    ok = await _send_outbound(
        channel=channel,
        conversation=conversation,
        contact=contact,
        text=payload.reply,
    )

    if not ok:
        logger.warning(f"[n8n-reply] Delivery failed for conversation {payload.conversation_id}")
        return {"ok": False, "error": "delivery_failed"}

    return {"ok": True}
