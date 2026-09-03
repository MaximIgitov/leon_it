"""Настройки приложения.

Единственный источник конфигурации — переменные окружения (и `.env` для локальной
разработки). Валидаторы не дают запустить прод с секретами по умолчанию: лучше
упасть на старте, чем подписывать токены известным ключом.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

_DEFAULT_JWT_SECRET = "change-me-local-only"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: Environment = "local"
    LOG_LEVEL: str = "INFO"
    API_PREFIX: str = "/api"
    # Публичный адрес сайта: из него собираются ссылки для кандидатов и писем.
    PUBLIC_URL: str = "http://localhost:3000"
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    DATABASE_URL: str = "sqlite+aiosqlite:///./leonit.db"
    # Куда складываются видео, аудио, снимки и резюме (см. core.storage).
    MEDIA_ROOT: Path = Path("./data/media")

    JWT_SECRET: str = _DEFAULT_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # /metrics отдаётся только с этим токеном; без него на проде ручка скрыта.
    METRICS_TOKEN: str | None = None

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_is_real_in_production(cls, value: str, info) -> str:
        if info.data.get("ENVIRONMENT") == "production":
            if value == _DEFAULT_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set to a real secret in production")
            if len(value) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _no_wildcard_cors_in_production(cls, value: list[str], info) -> list[str]:
        if info.data.get("ENVIRONMENT") == "production" and any(
            origin.strip() == "*" for origin in value
        ):
            raise ValueError("Wildcard CORS origin is not allowed in production")
        return value

    @field_validator("PUBLIC_URL")
    @classmethod
    def _public_url_without_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def sync_database_url(self) -> str:
        """URL для синхронных инструментов (Alembic offline, скрипты)."""
        if self.DATABASE_URL.startswith("postgresql+asyncpg://"):
            return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        if self.DATABASE_URL.startswith("sqlite+aiosqlite://"):
            return self.DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://", 1)
        return self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()
