"""Кандидаты, интервью (приглашение + прохождение) и журнал согласий.

Кандидат принадлежит организации и уникален по e-mail; интервью — одно
прохождение по одной вакансии. Статус интервью — state machine с таймстемпами
каждого перехода: те же таймстемпы кормят воронку дашборда.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leonit.core.db import Base, TimestampMixin, uuid_pk
from leonit.core.time import utcnow


class CandidateSource(enum.StrEnum):
    manual = "manual"
    bulk = "bulk"
    hh = "hh"
    huntflow = "huntflow"
    api = "api"


class InterviewStatus(enum.StrEnum):
    invited = "invited"
    opened = "opened"
    consented = "consented"
    in_progress = "in_progress"
    completed = "completed"
    processing = "processing"
    evaluated = "evaluated"
    reviewed = "reviewed"
    advanced = "advanced"
    rejected = "rejected"
    expired = "expired"
    cancelled = "cancelled"


# Разрешённые переходы. «Назад» нет: если кандидат вернулся по ссылке после
# consented, он остаётся в consented до старта записи.
TRANSITIONS: dict[InterviewStatus, frozenset[InterviewStatus]] = {
    InterviewStatus.invited: frozenset(
        {InterviewStatus.opened, InterviewStatus.expired, InterviewStatus.cancelled}
    ),
    InterviewStatus.opened: frozenset(
        {InterviewStatus.consented, InterviewStatus.expired, InterviewStatus.cancelled}
    ),
    InterviewStatus.consented: frozenset(
        {InterviewStatus.in_progress, InterviewStatus.expired, InterviewStatus.cancelled}
    ),
    InterviewStatus.in_progress: frozenset(
        {InterviewStatus.completed, InterviewStatus.expired, InterviewStatus.cancelled}
    ),
    InterviewStatus.completed: frozenset({InterviewStatus.processing, InterviewStatus.cancelled}),
    InterviewStatus.processing: frozenset(
        {InterviewStatus.evaluated, InterviewStatus.completed, InterviewStatus.cancelled}
    ),
    InterviewStatus.evaluated: frozenset(
        {
            InterviewStatus.reviewed,
            InterviewStatus.advanced,
            InterviewStatus.rejected,
            InterviewStatus.processing,
        }
    ),
    InterviewStatus.reviewed: frozenset({InterviewStatus.advanced, InterviewStatus.rejected}),
    InterviewStatus.advanced: frozenset({InterviewStatus.rejected}),
    InterviewStatus.rejected: frozenset({InterviewStatus.advanced}),
    InterviewStatus.expired: frozenset({InterviewStatus.invited}),
    InterviewStatus.cancelled: frozenset(),
}

# Статусы, в которых кандидат ещё не завершил прохождение.
OPEN_STATUSES = frozenset(
    {
        InterviewStatus.invited,
        InterviewStatus.opened,
        InterviewStatus.consented,
        InterviewStatus.in_progress,
    }
)


class Candidate(TimestampMixin, Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("organization_id", "email", name="uq_candidate_org_email"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[CandidateSource] = mapped_column(
        Enum(CandidateSource, name="candidate_source", native_enum=False, length=16),
        default=CandidateSource.manual,
        nullable=False,
    )
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resume_key: Mapped[str | None] = mapped_column(String(512))
    resume_filename: Mapped[str | None] = mapped_column(String(255))
    resume_text: Mapped[str | None] = mapped_column(Text)
    # Внешние идентификаторы для интеграций (HH, Huntflow).
    external_ref: Mapped[str | None] = mapped_column(String(128), index=True)
    # Согласие на рассылку вакансий (маркетинг) — отдельно от письма с обратной
    # связью по своему интервью: его кандидат ждёт, и оно уходит, пока он не
    # отписался явно (``unsubscribed_at``).
    newsletter_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    interviews: Mapped[list[Interview]] = relationship(back_populates="candidate")


class Interview(TimestampMixin, Base):
    __tablename__ = "interviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Ссылка кандидата: хранится только SHA-256 токена.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[InterviewStatus] = mapped_column(
        Enum(InterviewStatus, name="interview_status", native_enum=False, length=16),
        default=InterviewStatus.invited,
        nullable=False,
        index=True,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Когда кандидату ушло напоминание о скором истечении ссылки (один раз).
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Что кандидат подтвердил на странице согласий (может отличаться от карточки).
    consent_full_name: Mapped[str | None] = mapped_column(String(255))
    consent_email: Mapped[str | None] = mapped_column(String(320))
    newsletter_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_ip: Mapped[str | None] = mapped_column(String(64))
    consent_user_agent: Mapped[str | None] = mapped_column(String(512))

    # Снимок вопросов и настроек на момент старта: правки вакансии после этого
    # не меняют интервью, которое кандидат уже проходит.
    question_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    settings_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    current_question_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    client_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Решение человека — отдельно от рекомендации модели.
    decision: Mapped[str | None] = mapped_column(String(16))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    external_ref: Mapped[str | None] = mapped_column(String(128), index=True)

    candidate: Mapped[Candidate] = relationship(back_populates="interviews")


class ConsentRecord(Base):
    """Факт принятия документа: версия и хеш текста, время, адрес, браузер."""

    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
