"""Ответы кандидата и события во время интервью.

Ответ — одна попытка записи на один вопрос: оригинал видео хранится как есть,
попытки не удаляются (в отчёте видно число перезаписей), а «зачётной» считается
последняя завершённая. Серверные тайминги (когда вопрос показан, когда пришёл
каждый кусок, когда запись завершена) — «истины» для integrity-анализа: клиенту
их подделать нельзя.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk
from leonit.core.time import utcnow


class AnswerStatus(enum.StrEnum):
    recording = "recording"
    uploaded = "uploaded"
    processing = "processing"
    done = "done"
    failed = "failed"
    abandoned = "abandoned"


class Answer(TimestampMixin, Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("interview_id", "question_index", "attempt", name="uq_answer_attempt"),
        Index("ix_answers_interview_question", "interview_id", "question_index"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # id вопроса из снимка; у уточняющего вопроса — id исходного и parent_answer_id.
    question_id: Mapped[str | None] = mapped_column(String(64))
    parent_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL")
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[AnswerStatus] = mapped_column(
        Enum(AnswerStatus, name="answer_status", native_enum=False, length=16),
        default=AnswerStatus.recording,
        nullable=False,
    )

    media_key: Mapped[str | None] = mapped_column(String(512))
    media_content_type: Mapped[str | None] = mapped_column(String(128))
    media_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    upload_offset: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    audio_key: Mapped[str | None] = mapped_column(String(512))

    # Серверные тайминги.
    recording_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    first_chunk_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_chunk_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    client_duration_ms: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    transcript_text: Mapped[str | None] = mapped_column(Text)
    transcript_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    transcript_language: Mapped[str | None] = mapped_column(String(16))
    media_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    processing_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterviewEvent(Base):
    """Событие клиента или сервера во время интервью с обоими временами."""

    __tablename__ = "interview_events"
    __table_args__ = (Index("ix_interview_events_interview_kind", "interview_id", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    answer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL")
    )
    question_index: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="client", nullable=False)
    at_client_ms: Mapped[int | None] = mapped_column(BigInteger)
    at_server: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
