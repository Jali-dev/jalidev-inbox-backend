"""
Supabase service — all database operations for JaliDev Inbox.
Uses supabase-py (async via httpx under the hood).
"""

import logging
from typing import Any

from supabase import create_client, Client
from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client


# ─────────────────────────────────────────────
# Contacts
# ─────────────────────────────────────────────

async def upsert_contact(
    external_id: str,
    name: str,
    channel: str,
    phone: str | None = None,
) -> dict[str, Any]:
    """
    Insert or update a contact by external_id.
    Returns the contact record.
    """
    client = _get_client()
    data = {
        "external_id": external_id,
        "name": name,
        "channel": channel,
    }
    if phone:
        data["phone"] = phone

    resp = (
        client.table("contacts")
        .upsert(data, on_conflict="external_id")
        .execute()
    )
    return resp.data[0]


# ─────────────────────────────────────────────
# Conversations
# ─────────────────────────────────────────────

async def get_or_create_conversation(
    contact_id: str,
    channel: str,
    external_chat_id: str | None = None,
) -> dict[str, Any]:
    """
    Get the open conversation for a contact+channel, or create one.
    external_chat_id is required for Telegram (chat.id).
    """
    client = _get_client()

    # Try to find an open conversation
    query = (
        client.table("conversations")
        .select("*")
        .eq("contact_id", contact_id)
        .eq("channel", channel)
        .eq("status", "open")
        .limit(1)
    )
    resp = query.execute()

    if resp.data:
        conv = resp.data[0]
        # Update external_chat_id if not set
        if external_chat_id and not conv.get("external_chat_id"):
            update_resp = (
                client.table("conversations")
                .update({"external_chat_id": external_chat_id})
                .eq("id", conv["id"])
                .execute()
            )
            return update_resp.data[0]
        return conv

    # Create new conversation
    new_conv: dict[str, Any] = {
        "contact_id": contact_id,
        "channel": channel,
        "status": "open",
        "is_ai_active": True,
    }
    if external_chat_id:
        new_conv["external_chat_id"] = external_chat_id

    create_resp = client.table("conversations").insert(new_conv).execute()
    return create_resp.data[0]


async def get_conversation_with_contact(
    conversation_id: str,
) -> dict[str, Any] | None:
    """
    Returns {"conversation": {...}, "contact": {...}} or None.
    """
    client = _get_client()
    resp = (
        client.table("conversations")
        .select("*, contacts(*)")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None

    row = resp.data[0]
    contact = row.pop("contacts", None)
    return {"conversation": row, "contact": contact or {}}


# ─────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────

async def save_inbound_message(
    conversation_id: str,
    content: str,
    external_message_id: str | None = None,
) -> dict[str, Any]:
    """
    Save an inbound message from the contact.
    """
    client = _get_client()
    data: dict[str, Any] = {
        "conversation_id": conversation_id,
        "content": content,
        "direction": "inbound",
        "sender_type": "contact",
        "status": "delivered",
    }
    if external_message_id:
        data["external_message_id"] = external_message_id

    resp = client.table("messages").insert(data).execute()
    return resp.data[0]


async def save_outbound_message(
    conversation_id: str,
    content: str,
    sender_type: str = "bot",  # "bot" | "agent"
) -> dict[str, Any]:
    """
    Save an outbound message (AI reply or agent reply).
    """
    client = _get_client()
    data = {
        "conversation_id": conversation_id,
        "content": content,
        "direction": "outbound",
        "sender_type": sender_type,
        "status": "sent",
    }
    resp = client.table("messages").insert(data).execute()
    return resp.data[0]
