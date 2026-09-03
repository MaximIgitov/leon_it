"""Вакансии, рубрика компетенций и вопросы интервью.

Вакансия — единица настройки интервью: описание и требования дают контекст
модели-оценщику, рубрика задаёт, по каким компетенциям и с какими якорными
уровнями оценивать, вопросы — что спрашивать и с какими лимитами времени.
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


class VacancyStatus(enum.StrEnum):
    draft = "draft"
    published = "published"
    archived = "archived"


class QuestionKind(enum.StrEnum):
    video = "video"
    # Задел под секцию кода: тип хранится и валидируется уже сейчас, редактор и
    # раннер появятся за фиче-флагом позже.
    code = "code"


class CandidateFeedbackMode(enum.StrEnum):
    off = "off"
    after_decision = "after_decision"
    auto_after_days = "auto_after_days"


class Vacancy(TimestampMixin, Base):
    __tablename__ = "vacancies"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    requirements: Mapped[str] = mapped_column(Text, default="", nullable=False)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    level: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    status: Mapped[VacancyStatus] = mapped_column(
        Enum(VacancyStatus, name="vacancy_status", native_enum=False, length=16),
        default=VacancyStatus.draft,
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Рубрика: [{id, name, description, weight, levels: {"1": ..., "4": ...}}].
    rubric: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # --- настройки интервью ---
    intro_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prep_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_answer_seconds: Mapped[int] = mapped_column(Integer, default=180, nullable=False)
    retakes_allowed: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    practice_question_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    followups_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    followups_max: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice: Mapped[str] = mapped_column(String(64), default="alloy", nullable=False)
    invitation_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    candidate_feedback_mode: Mapped[CandidateFeedbackMode] = mapped_column(
        Enum(CandidateFeedbackMode, name="candidate_feedback_mode", native_enum=False, length=24),
        default=CandidateFeedbackMode.after_decision,
        nullable=False,
    )
    candidate_feedback_after_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    questions: Mapped[list[Question]] = relationship(
        back_populates="vacancy",
        cascade="all, delete-orphan",
        order_by="Question.position",
    )


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("vacancy_id", "position", name="uq_question_position"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[QuestionKind] = mapped_column(
        Enum(QuestionKind, name="question_kind", native_enum=False, length=16),
        default=QuestionKind.video,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Что должен покрыть хороший ответ — подсказка оценщику, кандидату не видна.
    expected_points: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    competency_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allows_followup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Переопределения лимитов вакансии; None — берём из вакансии.
    prep_seconds: Mapped[int | None] = mapped_column(Integer)
    max_answer_seconds: Mapped[int | None] = mapped_column(Integer)
    retakes_allowed: Mapped[int | None] = mapped_column(Integer)

    vacancy: Mapped[Vacancy] = relationship(back_populates="questions")
