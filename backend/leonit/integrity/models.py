"""Решение ревьюера по наблюдению достоверности.

Сами наблюдения не хранятся: они выводятся из событий и метаданных при каждом
чтении отчёта, поэтому изменение правил сразу видно на старых интервью. А вот
вердикт человека («подтверждаю» / «ложное срабатывание») — факт, и он живёт в
своей таблице: по паре «интервью + код наблюдения + вопрос».
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk


class IntegrityVerdict(enum.StrEnum):
    confirmed = "confirmed"
    false_positive = "false_positive"


class IntegrityReview(TimestampMixin, Base):
    __tablename__ = "integrity_reviews"
    __table_args__ = (
        UniqueConstraint(
            "interview_id",
            "code",
            "question_index",
            name="uq_integrity_review_observation",
        ),
        Index("ix_integrity_reviews_interview", "interview_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    # -1 — наблюдение по интервью целиком: NULL в уникальном ключе не работает.
    question_index: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    verdict: Mapped[IntegrityVerdict] = mapped_column(
        Enum(IntegrityVerdict, name="integrity_verdict", native_enum=False, length=16),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewer_label: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
