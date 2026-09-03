from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Scope = Literal[
    "vacancies:read",
    "vacancies:write",
    "candidates:read",
    "candidates:write",
    "interviews:read",
    "reports:read",
    "media:read",
]
TokenStatus = Literal["active", "expired", "revoked"]


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="Для чего токен: «Huntflow», «CI».")
    scopes: list[Scope] = Field(min_length=1, description="Области доступа.")
    # None — бессрочный: интеграции живут дольше любого разумного срока, а отзыв
    # доступен в любой момент.
    expires_in_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Укажите название токена")
        return value

    @field_validator("scopes")
    @classmethod
    def _unique(cls, value: list[Scope]) -> list[Scope]:
        return list(dict.fromkeys(value))


class ApiTokenOut(BaseModel):
    id: str
    name: str
    token_prefix: str
    scopes: list[str]
    created_by_user_id: str | None
    created_by_email: str | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    status: TokenStatus


class ApiTokenCreated(ApiTokenOut):
    # Единственный ответ, в котором есть сам токен: дальше хранится только хеш.
    token: str
