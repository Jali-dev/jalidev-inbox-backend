"""
App configuration — pydantic-settings v2.
All values come from environment variables (or .env file).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Supabase ─────────────────────────────
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # ── Telegram ─────────────────────────────
    # Get from @BotFather → /newbot
    TELEGRAM_BOT_TOKEN: str = ""

    # ── Meta / WhatsApp Cloud API ─────────────
    # Leave empty until you have Meta Business credentials
    META_PHONE_NUMBER_ID: str = ""
    META_ACCESS_TOKEN: str = ""
    META_APP_SECRET: str = ""
    META_VERIFY_TOKEN: str = "jalidev-inbox-verify"

    # ── n8n ──────────────────────────────────
    # WF-06 webhook URL (created: JALIDEV | 06 - Inbox AI Reply)
    N8N_INBOX_WEBHOOK_URL: str = "https://n8n.jalidev.online/webhook/inbox-ai-reply"
    # Secret key that n8n sends back in X-Callback-Key header
    N8N_CALLBACK_KEY: str = "change-me-to-a-random-secret"

    # ── FastAPI ───────────────────────────────
    # Public base URL of this FastAPI server (used to register Telegram webhook)
    FASTAPI_BASE_URL: str = "https://api.jalidev.online"


settings = Settings()
