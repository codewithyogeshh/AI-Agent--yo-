"""Central, typed configuration. Everything is env-driven; nothing is hardcoded."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "NOVA"
    env: str = Field("development", validation_alias=AliasChoices("NOVA_ENV", "ENV"))
    secret_key: str = Field(
        "dev-only-insecure-key-change-me", validation_alias=AliasChoices("NOVA_SECRET_KEY", "SECRET_KEY")
    )
    access_token_minutes: int = Field(
        720, validation_alias=AliasChoices("NOVA_ACCESS_TOKEN_MINUTES", "ACCESS_TOKEN_MINUTES")
    )

    database_url: str = "sqlite:///./data/nova.db"
    public_base_url: str = ""
    workspace_dir: Path = Field(
        Path("./data/workspace"), validation_alias=AliasChoices("NOVA_WORKSPACE_DIR", "WORKSPACE_DIR")
    )
    cors_origins_raw: str = Field(
        "http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("NOVA_CORS_ORIGINS", "CORS_ORIGINS"),
    )

    # AI providers
    ai_provider: str = Field("", validation_alias=AliasChoices("NOVA_AI_PROVIDER", "AI_PROVIDER"))
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-latest"

    # Auth
    supabase_url: str = ""
    supabase_jwt_secret: str = ""

    # One-click managed social connect (Upload-Post holds the platform OAuth apps)
    upload_post_api_key: str = ""

    # WhatsApp
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_allowed_numbers: str = ""

    # Google / YouTube
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/integrations/google/callback"

    # Meta / Instagram
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_redirect_uri: str = "http://localhost:8000/api/integrations/instagram/callback"

    # Media
    ffmpeg_path: str = "ffmpeg"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    openai_tts_voice: str = "alloy"

    # Worker
    worker_enabled: bool = Field(True, validation_alias=AliasChoices("NOVA_WORKER_ENABLED", "WORKER_ENABLED"))
    worker_concurrency: int = Field(
        2, validation_alias=AliasChoices("NOVA_WORKER_CONCURRENCY", "WORKER_CONCURRENCY")
    )
    scheduler_enabled: bool = Field(
        True, validation_alias=AliasChoices("NOVA_SCHEDULER_ENABLED", "SCHEDULER_ENABLED")
    )

    # Desktop bridge
    desktop_bridge_token: str = ""
    desktop_allowed_commands: str = "git status,npm test,python --version,ls,df -h"

    @property
    def cors_origins(self) -> List[str]:
        return _split_csv(self.cors_origins_raw)

    @property
    def whatsapp_allowed(self) -> List[str]:
        return [n.replace(" ", "") for n in _split_csv(self.whatsapp_allowed_numbers)]

    @property
    def desktop_allowlist(self) -> List[str]:
        return _split_csv(self.desktop_allowed_commands)

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    def ensure_dirs(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            db_path = self.database_url.split("sqlite:///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
