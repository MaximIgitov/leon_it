"""Заключение по интервью.

Одна строка на интервью (``interview_id`` уникален): переоценка перезаписывает
её, а не добавляет новую — рекрутер видит один актуальный результат, история
попыток остаётся в задачах очереди. Сырой ответ модели и usage хранятся рядом,
чтобы разбирать спорные оценки и считать расходы без повторных запросов.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk


class EvaluationStatus(enum.StrEnum):
    pending = "pending"
    done = "done"
    failed = "failed"


class Evaluation(TimestampMixin, Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = uuid_pk()
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    status: Mapped[EvaluationStatus] = mapped_column(
        Enum(EvaluationStatus, name="evaluation_status", native_enum=False, length=16),
        default=EvaluationStatus.pending,
        nullable=False,
    )
    # 0..100, считается детерминированно из баллов (см. scoring.py).
    fit_score: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(String(16))
    # EvaluationOutput.model_dump(): заключение целиком, с цитатами.
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    candidate_feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
