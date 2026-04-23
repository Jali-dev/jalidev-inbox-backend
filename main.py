"""
JaliDev Inbox Backend — FastAPI entry point.

Channels supported: Telegram, WhatsApp (Meta Cloud API)
AI: n8n WF-06 → OpenRouter / DeepSeek
Storage: Supabase (PostgreSQL + Realtime)
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import messages, webhooks_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

app = FastAPI(
    title="JaliDev Inbox Backend",
    description="Multi-channel inbox backend: Telegram + WhatsApp + AI via n8n",
    version="1.0.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(messages.router)
app.include_router(webhooks_telegram.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "service": "jalidev-inbox-backend"}
