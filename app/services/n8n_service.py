"""
n8n service — triggers WF-06 (Inbox AI Reply) for AI-generated responses.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.services import supabase_service

logger = logging.getLogger(__name__)


async def trigger_ai_workflow(
    conversation_id: str,
    contact_name: str,
    message: str,
    channel: str,
    extra: dict[str, Any] | None = None,
) -> bool:
    """
    POST to WF-06 webhook to trigger AI reply generation.

    n8n will call back /api/internal/n8n-reply with the generated reply.

    Args:
        conversation_id: UUID of the conversation in Supabase.
        contact_name:    Display name of the contact (for the LLM prompt).
        message:         Inbound message text.
        channel:         "telegram" | "whatsapp"
        extra:           Channel-specific extras (e.g. {"telegram_chat_id": "123"})
    """
    callback_url = f"{settings.FASTAPI_BASE_URL}/api/internal/n8n-reply"

    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "contact_name": contact_name,
        "message": message,
        "channel": channel,
        "callback_url": callback_url,
        "callback_key": settings.N8N_CALLBACK_KEY,
    }

    workspace_id = None
    if extra:
        workspace_id = extra.get("workspace_id")

    if not workspace_id:
        workspace_id = (
            await supabase_service.resolve_workspace_id_for_conversation(conversation_id)
            or await supabase_service.resolve_workspace_id_for_channel(channel)
        )

    if workspace_id:
        payload["workspace_id"] = workspace_id
        workspace_runtime = await supabase_service.get_workspace_ai_runtime(str(workspace_id))
        if workspace_runtime:
            payload.update({
                "workspace_ai_model": workspace_runtime.get("ai_model"),
                "workspace_plan_id": workspace_runtime.get("plan_id"),
                "workspace_subscription_status": workspace_runtime.get("subscription_status"),
                "workspace_system_prompt": workspace_runtime.get("system_prompt"),
                "workspace_max_tokens": workspace_runtime.get("max_tokens"),
                "workspace_temperature": workspace_runtime.get("temperature"),
            })

    if extra:
        payload.update(extra)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(settings.N8N_INBOX_WEBHOOK_URL, json=payload)
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.exception(f"[n8n] Failed to trigger AI workflow: {exc}")
        return False
