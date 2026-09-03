"""Заметки ревьюеров, ссылки на отчёт для нанимающего менеджера и аудит просмотров.

Ссылка на отчёт — самостоятельный доступ без аккаунта: один кандидат, срок,
отзыв и журнал просмотров. Как и все токены ссылок, хранится только хешем.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk
from leonit.core.time import utcnow


class ReviewNote(TimestampMixin, Base):
    __tablename__ = "review_notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Заметка может быть от гостя по ссылке отчёта — тогда author_user_id пуст.
    author_label: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Привязка к моменту видео: ответ и секунда — заметка ведёт к цитате.
    answer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL")
    )
    at_s: Mapped[float | None] = mapped_column()


class ReportShare(TimestampMixin, Base):
    __tablename__ = "report_shares"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Детали integrity и другие кандидаты по ссылке не видны, если не включено явно.
    include_integrity: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_download: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportView(Base):
    """Кто и что открывал по ссылке отчёта — виден рекрутеру в карточке."""

    __tablename__ = "report_views"

    id: Mapped[uuid.UUID] = uuid_pk()
    share_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_shares.id", ondelete="CASCADE"), index=True, nullable=False
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    what: Mapped[str] = mapped_column(String(32), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
