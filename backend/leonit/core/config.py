"""Настройки приложения.

Единственный источник конфигурации — переменные окружения (и `.env` для локальной
разработки). Валидаторы не дают запустить прод с секретами по умолчанию: лучше
упасть на старте, чем подписывать токены известным ключом.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
ModelProvider = Literal["openai_compatible", "fake"]
# Провайдеры добавляются в реестры leonit.avatar / leonit.code_runner и в эти
# Literal; "heygen" — leonit.avatar.providers.heygen.
AvatarProvider = Literal["none", "heygen"]
CodeRunnerKind = Literal["none"]

# Роли моделей: у каждой свой набор MODEL_<ROLE>_* переменных (см. leonit.ai.config).
MODEL_ROLES: tuple[str, ...] = ("evaluator", "assistant", "interviewer", "stt", "tts")

_DEFAULT_JWT_SECRET = "change-me-local-only"
# OpenAI-совместимый агрегатор, доступный из РФ и умеющий /audio/*; OpenRouter
# /audio/* не умеет, поэтому base_url задаётся на роль, а не глобально.
_DEFAULT_MODEL_BASE_URL = "https://api.aitunnel.ru/v1"


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

    # Страница документации публичного API (/api/docs/api, Scalar). В отличие от
    # Swagger кабинета, она нужна и на проде: её читают интеграторы.
    PUBLIC_API_DOCS_ENABLED: bool = True

    # Ключ Fernet для секретов интеграций в БД (см. core.crypto); вторичные —
    # для ротации, через запятую. Вне production пустой ключ выводится из JWT_SECRET.
    DATA_ENCRYPTION_KEY: str = ""
    DATA_ENCRYPTION_KEYS_SECONDARY: str = ""

    # --- Кандидатский флоу и письма ------------------------------------------
    # Контакт оператора в юридических текстах и письмах.
    SUPPORT_EMAIL: str = "info@napoleonit.ru"
    # Срок хранения медиа по умолчанию (подставляется в тексты; у организации свой).
    DEFAULT_RETENTION_DAYS: int = 180
    # console — письма только в outbox и логи (стенд без SMTP); smtp — реальная отправка.
    EMAIL_MODE: Literal["console", "smtp"] = "console"
    EMAIL_FROM: str = "LeonIT <no-reply@leonit.local>"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = True

    # --- Ассистент ------------------------------------------------------------
    # Сколько tool-вызовов подряд может сделать агент за один ход: защита от
    # зацикливания модели, а не продуктовый лимит.
    ASSISTANT_MAX_STEPS: int = 8
    # Сколько последних сообщений треда уходит в контекст модели.
    ASSISTANT_HISTORY_LIMIT: int = 40

    # --- Медиа-пайплайн --------------------------------------------------------
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"
    # Потолок на один вызов ffmpeg: ответ на минуты обрабатывается за секунды,
    # десять минут — это уже зависший процесс, который нужно убить.
    FFMPEG_TIMEOUT_S: int = 600
    # Час (UTC), в который воркер запускает ежедневную чистку медиа по сроку хранения.
    RETENTION_PURGE_HOUR_UTC: int = Field(default=3, ge=0, le=23)
    # Ответ в статусе processing без изменений дольше этого срока считается
    # брошенным (воркер убит без graceful stop) и берётся в обработку заново.
    PIPELINE_STALE_PROCESSING_S: int = Field(default=1800, ge=60)

    # --- HH.ru (см. leonit.hh) ------------------------------------------------
    # Без ключей интеграция работает в fake-режиме на фикстурах; real включается
    # по наличию HH_CLIENT_ID и HH_CLIENT_SECRET (или явно через HH_MODE).
    HH_MODE: Literal["auto", "fake", "real"] = "auto"
    HH_CLIENT_ID: str | None = None
    HH_CLIENT_SECRET: str | None = None
    # None — PUBLIC_URL + API_PREFIX + /integrations/hh/callback (см. hh_redirect_url).
    HH_REDIRECT_URL: str | None = None
    HH_API_BASE: str = "https://api.hh.ru"
    HH_OAUTH_BASE: str = "https://hh.ru"
    HH_USER_AGENT: str = "LeonIT/1.0 (info@napoleonit.ru)"
    HH_SYNC_INTERVAL_MINUTES: int = Field(default=10, ge=1, le=1440)
    # --- Huntflow -------------------------------------------------------------
    HUNTFLOW_API_BASE: str = "https://api.huntflow.ru/v2"
    # auto — реальный клиент при подключении по токену, фейковый при «Подключить
    # демо»; fake — всегда фикстуры (стенд без ключей, CI); real — демо запрещено.
    HUNTFLOW_MODE: Literal["auto", "fake", "real"] = "auto"
    HUNTFLOW_TIMEOUT_S: float = Field(default=15, gt=0)

    # --- Шлюз к моделям -------------------------------------------------------
    # None — выбрать автоматически: fake, если ни у одной роли нет ключа, иначе
    # openai_compatible. Так CI и e2e работают без ключей и сети, а стенд с
    # ключами ничего дополнительно не настраивает.
    MODEL_PROVIDER: ModelProvider | None = None
    MODEL_ALLOW_FAKE_IN_PRODUCTION: bool = False
    # Фолбэк для ролей, у которых нет собственных MODEL_<ROLE>_* значений.
    MODEL_DEFAULT_BASE_URL: str = _DEFAULT_MODEL_BASE_URL
    MODEL_DEFAULT_API_KEY: str | None = None
    MODEL_DEFAULT_PROXY_URL: str | None = None
    # Лимит генерации (max_tokens). Агрегаторы прогнозируют цену запроса по
    # max_tokens, а без него — по максимуму модели, и при низком балансе
    # отклоняют запрос ещё до генерации (HTTP 402). Умолчания по ролям —
    # в leonit.ai.config.
    MODEL_DEFAULT_MAX_TOKENS: int | None = None

    MODEL_EVALUATOR_BASE_URL: str | None = None
    MODEL_EVALUATOR_API_KEY: str | None = None
    MODEL_EVALUATOR_MODEL: str = "claude-sonnet-5"
    MODEL_EVALUATOR_PROXY_URL: str | None = None
    MODEL_EVALUATOR_TIMEOUT_S: float | None = None
    MODEL_EVALUATOR_MAX_TOKENS: int | None = None

    MODEL_ASSISTANT_BASE_URL: str | None = None
    MODEL_ASSISTANT_API_KEY: str | None = None
    MODEL_ASSISTANT_MODEL: str = "claude-sonnet-5"
    MODEL_ASSISTANT_PROXY_URL: str | None = None
    MODEL_ASSISTANT_TIMEOUT_S: float | None = None
    MODEL_ASSISTANT_MAX_TOKENS: int | None = None

    MODEL_INTERVIEWER_BASE_URL: str | None = None
    MODEL_INTERVIEWER_API_KEY: str | None = None
    MODEL_INTERVIEWER_MODEL: str = "claude-haiku-4.5"
    MODEL_INTERVIEWER_PROXY_URL: str | None = None
    MODEL_INTERVIEWER_TIMEOUT_S: float | None = None
    MODEL_INTERVIEWER_MAX_TOKENS: int | None = None

    MODEL_STT_BASE_URL: str | None = None
    MODEL_STT_API_KEY: str | None = None
    MODEL_STT_MODEL: str = "gpt-4o-transcribe"
    MODEL_STT_PROXY_URL: str | None = None
    MODEL_STT_TIMEOUT_S: float | None = None

    MODEL_TTS_BASE_URL: str | None = None
    MODEL_TTS_API_KEY: str | None = None
    MODEL_TTS_MODEL: str = "gpt-4o-mini-tts"
    MODEL_TTS_PROXY_URL: str | None = None
    MODEL_TTS_TIMEOUT_S: float | None = None

    # --- Оценка интервью ------------------------------------------------------
    # Пороги рекомендации по fit_score (0..100): ≥ FIT — «подходит»,
    # < NO_FIT — «не подходит», между ними — «нужна проверка».
    EVAL_FIT_THRESHOLD: float = 70
    EVAL_NO_FIT_THRESHOLD: float = 45

    # --- ИИ-аватар и секция кода (задел, см. leonit.avatar и leonit.code_runner) ---
    # Аватар показывается в комнате, только если флаг включён и провайдер не "none".
    AVATAR_ENABLED: bool = False
    AVATAR_PROVIDER: AvatarProvider = "none"
    # HeyGen (developers.heygen.com), кошелёк pay-as-you-go. Образ — id из
    # GET /v3/avatars/looks (публичные студийные образы поддерживают avatar_iii),
    # голос — voice_id из GET /v3/voices?language=Russian.
    AVATAR_HEYGEN_API_KEY: str | None = None
    AVATAR_HEYGEN_BASE_URL: str = "https://api.heygen.com"
    AVATAR_HEYGEN_AVATAR_ID: str = "Daphne_public_1"
    AVATAR_HEYGEN_VOICE_ID: str = "37832e32d4f7475ab7a1cb0db8e5dd66"  # Anya, русский
    # avatar_iii — самый дешёвый движок (около $1 за минуту видео), avatar_iv в разы дороже.
    AVATAR_HEYGEN_ENGINE: Literal["avatar_iii", "avatar_iv", "avatar_v"] = "avatar_iii"
    AVATAR_HEYGEN_RESOLUTION: Literal["720p", "1080p"] = "720p"
    AVATAR_HEYGEN_TIMEOUT_S: float = Field(default=420.0, gt=0, le=1800)
    AVATAR_HEYGEN_POLL_S: float = Field(default=5.0, gt=0, le=60)
    # Экономия: вопрос длиннее лимита не рендерится — минута видео стоит денег.
    AVATAR_MAX_TEXT_CHARS: int = Field(default=600, ge=50, le=5000)
    # Запуск кода кандидата: "none" — редактор работает, кнопка «Запустить» выключена.
    CODE_RUNNER: CodeRunnerKind = "none"
    CODE_RUNNER_TIMEOUT_S: float = Field(default=10.0, gt=0, le=120)
    CODE_LANGUAGES: list[str] = Field(
        default_factory=lambda: ["python", "javascript", "typescript", "go", "java", "sql"]
    )
    CODE_MAX_SOURCE_BYTES: int = Field(default=65536, ge=1024)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def model_role_value(self, role: str, name: str) -> object:
        """Значение MODEL_<ROLE>_<NAME> (без фолбэков; их применяет leonit.ai.config)."""
        return getattr(self, f"MODEL_{role.upper()}_{name.upper()}")

    def model_role_api_key(self, role: str) -> str | None:
        return self.model_role_value(role, "API_KEY") or self.MODEL_DEFAULT_API_KEY

    @property
    def effective_hh_mode(self) -> Literal["fake", "real"]:
        if self.HH_MODE != "auto":
            return self.HH_MODE
        return "real" if self.HH_CLIENT_ID and self.HH_CLIENT_SECRET else "fake"

    @property
    def hh_redirect_url(self) -> str:
        default = f"{self.PUBLIC_URL}{self.API_PREFIX}/integrations/hh/callback"
        return self.HH_REDIRECT_URL or default

    @property
    def effective_model_provider(self) -> ModelProvider:
        if self.MODEL_PROVIDER is not None:
            return self.MODEL_PROVIDER
        if any(self.model_role_api_key(role) for role in MODEL_ROLES):
            return "openai_compatible"
        return "fake"

    @model_validator(mode="after")
    def _no_fake_models_in_production(self) -> Settings:
        # Фейковый провайдер на проде означает, что кандидатов «оценивает» заглушка;
        # включить это можно только явно, чтобы не выкатить стенд без ключей.
        if (
            self.is_production
            and self.effective_model_provider == "fake"
            and not self.MODEL_ALLOW_FAKE_IN_PRODUCTION
        ):
            raise ValueError(
                "MODEL_PROVIDER=fake is not allowed in production "
                "(set MODEL_*_API_KEY or MODEL_ALLOW_FAKE_IN_PRODUCTION=true)"
            )
        return self

    @model_validator(mode="after")
    def _eval_thresholds_are_ordered(self) -> Settings:
        if not 0 <= self.EVAL_NO_FIT_THRESHOLD < self.EVAL_FIT_THRESHOLD <= 100:
            raise ValueError(
                "EVAL_NO_FIT_THRESHOLD must be lower than EVAL_FIT_THRESHOLD, both within 0..100"
            )
        return self

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_is_real_in_production(cls, value: str, info) -> str:
        if info.data.get("ENVIRONMENT") == "production":
            if value == _DEFAULT_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set to a real secret in production")
            if len(value) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return value

    @field_validator("DATA_ENCRYPTION_KEY")
    @classmethod
    def _encryption_key_is_set_in_production(cls, value: str, info) -> str:
        if info.data.get("ENVIRONMENT") == "production" and not value:
            raise ValueError("DATA_ENCRYPTION_KEY must be set in production")
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
