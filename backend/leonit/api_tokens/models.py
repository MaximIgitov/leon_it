"""API-токены организации для публичного API.

Токен показывается один раз при создании и хранится только хешем (SHA-256):
утечка базы не даёт доступа к API. Префикс ``leonit_`` нужен secret-scanning
(GitHub, GitLab): токен, случайно попавший в репозиторий, распознаётся по
шаблону. Первые символы хранятся отдельно, чтобы владелец мог отличить токены
в списке, не видя их целиком.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk


class ApiToken(TimestampMixin, Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Первые 12 символов («leonit_AbCdE») — для показа в списке.
    token_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Области доступа: см. leonit.api_tokens.scopes.
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # None — бессрочный токен.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Обновляется не чаще раза в минуту: каждый запрос API не должен писать в базу.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
