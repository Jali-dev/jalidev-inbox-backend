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
DEFAULT_INBOX_AI_CREDIT_COST = 1


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client


def _telegram_runtime_bot_id() -> str | None:
    token = (settings.TELEGRAM_BOT_TOKEN or '').strip()
    if not token or ':' not in token:
        return None
    bot_id = token.split(':', 1)[0].strip()
    return bot_id or None


def _extract_telegram_bot_id(external_id: str | None) -> str | None:
    if not external_id:
        return None

    parts = str(external_id).split(':')
    if len(parts) >= 3 and parts[0] == 'tg' and parts[1]:
        return parts[1]

    return None


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


async def resolve_workspace_id_for_conversation(conversation_id: str) -> str | None:
    """
    Resolve workspace ownership from the conversation contact identity.
    This matches the inbox-lite logic used in the Next.js app.
    """
    conv_data = await get_conversation_with_contact(conversation_id)
    if not conv_data:
        return None

    contact = conv_data["contact"] or {}
    external_id = contact.get("external_id")
    phone = contact.get("phone")

    client = _get_client()

    if external_id:
        if external_id.startswith("tg:"):
            parts = external_id.split(":")
            if len(parts) >= 3 and parts[1]:
                workspace_channel_resp = (
                    client.table("workspace_channels")
                    .select("workspace_id")
                    .eq("channel_type", "telegram")
                    .eq("external_id", f"telegram:{parts[1]}")
                    .limit(1)
                    .execute()
                )
                if workspace_channel_resp.data:
                    workspace_id = workspace_channel_resp.data[0].get("workspace_id")
                    if workspace_id:
                        return str(workspace_id)

        identity_resp = (
            client.table("client_channel_identities")
            .select("workspace_id")
            .eq("sender_key", str(external_id))
            .limit(1)
            .execute()
        )
        if identity_resp.data:
            workspace_id = identity_resp.data[0].get("workspace_id")
            if workspace_id:
                return str(workspace_id)

    if phone:
        client_resp = (
            client.table("clients")
            .select("workspace_id")
            .eq("phone", str(phone))
            .limit(1)
            .execute()
        )
        if client_resp.data:
            workspace_id = client_resp.data[0].get("workspace_id")
            if workspace_id:
                return str(workspace_id)

    return None


async def resolve_telegram_bot_token_for_conversation(conversation_id: str) -> str | None:
    conv_data = await get_conversation_with_contact(conversation_id)
    if not conv_data:
        return None

    contact = conv_data["contact"] or {}
    external_id = contact.get("external_id")
    bot_id = _extract_telegram_bot_id(external_id)
    if not bot_id:
        bot_id = _telegram_runtime_bot_id()

    if not bot_id:
        return None

    client = _get_client()
    resp = (
        client.table("workspace_channels")
        .select("config")
        .eq("channel_type", "telegram")
        .eq("external_id", f"telegram:{bot_id}")
        .limit(1)
        .execute()
    )

    if not resp.data:
        return None

    config = resp.data[0].get("config") or {}
    token = config.get("bot_token") if isinstance(config, dict) else None
    return str(token).strip() if token else None


async def resolve_workspace_id_for_channel(channel: str) -> str | None:
    """
    Resolve the workspace that owns the active channel.
    Current inbox-backend traffic is single-workspace per channel,
    so the connected workspace_channel is the source of truth.
    """
    client = _get_client()

    if channel == "telegram":
        bot_id = _telegram_runtime_bot_id()
        if bot_id:
            resp = (
                client.table("workspace_channels")
                .select("workspace_id")
                .eq("channel_type", "telegram")
                .eq("external_id", f"telegram:{bot_id}")
                .eq("status", "connected")
                .limit(1)
                .execute()
            )

            if resp.data:
                workspace_id = resp.data[0].get("workspace_id")
                if workspace_id:
                    return str(workspace_id)

    resp = (
        client.table("workspace_channels")
        .select("workspace_id")
        .eq("channel_type", channel)
        .eq("status", "connected")
        .limit(1)
        .execute()
    )

    if not resp.data:
        return None

    workspace_id = resp.data[0].get("workspace_id")
    return str(workspace_id) if workspace_id else None


async def get_workspace_ai_runtime(workspace_id: str) -> dict[str, Any] | None:
    """
    Load the workspace AI runtime settings used by WF-06.
    """
    client = _get_client()
    resp = (
        client.table("workspaces")
        .select("id, ai_model, plan_id, subscription_status, system_prompt, max_tokens, temperature")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    )

    if not resp.data:
        return None

    return resp.data[0]


async def consume_workspace_credits(workspace_id: str, cost: int = DEFAULT_INBOX_AI_CREDIT_COST) -> bool:
    """
    Deduct credits using the financial RPC.
    Returns True when the deduction succeeds.
    """
    client = _get_client()
    resp = client.rpc(
        "check_and_consume_credit",
        {"p_workspace_id": workspace_id, "p_cost": max(int(cost), 0)},
    ).execute()
    return bool(resp.data)


async def increment_workspace_analytics(workspace_id: str, credits_used: int = DEFAULT_INBOX_AI_CREDIT_COST) -> None:
    """
    Best-effort analytics update for AI replies.
    """
    client = _get_client()
    client.rpc(
        "increment_analytics",
        {"p_workspace_id": workspace_id, "p_credits_used": max(int(credits_used), 0)},
    ).execute()


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
