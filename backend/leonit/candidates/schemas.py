from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

InterviewStatusLiteral = Literal[
    "invited",
    "opened",
    "consented",
    "in_progress",
    "completed",
    "processing",
    "evaluated",
    "reviewed",
    "advanced",
    "rejected",
    "expired",
    "cancelled",
]
SourceLiteral = Literal["manual", "bulk", "hh", "huntflow", "api"]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class CandidateCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=64)
    notes: str = Field(default="", max_length=4000)
    # Идентификатор во внешней системе (HH, Huntflow, своя ATS через API).
    external_ref: str | None = Field(default=None, max_length=128)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class CandidateUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)


class CandidateBulkCreate(BaseModel):
    """Массовое добавление: по кандидату на строку — «Имя Фамилия, email» или «email»."""

    text: str = Field(min_length=1, max_length=100_000)
    vacancy_id: UUID | None = None

    @field_validator("vacancy_id", mode="before")
    @classmethod
    def _empty_as_none(cls, value: object) -> object:
        # Диалог кабинета шлёт пустую строку, когда вакансия не выбрана.
        return None if value == "" else value

    def parse(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for raw in self.text.splitlines():
            line = raw.strip()
            if not line:
                continue
            match = _EMAIL_RE.search(line)
            if not match:
                continue
            email = match.group(0).lower()
            name = re.sub(r"[,;\t]+", " ", line.replace(match.group(0), "")).strip(" ,;\t")
            rows.append((name or email.split("@", 1)[0], email))
        return rows


class CandidateOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    phone: str | None
    source: SourceLiteral
    notes: str
    has_resume: bool
    newsletter_opt_in: bool
    external_ref: str | None
    created_at: datetime
    interview_count: int = 0
    last_interview_status: InterviewStatusLiteral | None = None


class BulkCreateResult(BaseModel):
    created: list[CandidateOut]
    existing: list[CandidateOut]
    skipped_lines: int
    invited: int = 0


class InviteRequest(BaseModel):
    # UUID проверяет pydantic: неверный формат — 422, а не ValueError в сервисе.
    vacancy_id: UUID
    candidate_id: UUID | None = None
    # Либо существующий кандидат, либо новый по имени и e-mail.
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    send_email: bool = True


class InterviewOut(BaseModel):
    id: str
    status: InterviewStatusLiteral
    vacancy_id: str
    vacancy_title: str
    candidate_id: str
    candidate_name: str
    candidate_email: EmailStr
    invited_at: datetime
    expires_at: datetime
    opened_at: datetime | None
    consented_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    evaluated_at: datetime | None
    decided_at: datetime | None
    decision: str | None
    current_question_index: int
    question_count: int | None
    # Итог заключения — чтобы список кандидатов был рабочим без перехода в карточку.
    fit_score: float | None = None
    recommendation: str | None = None
    confidence: float | None = None
    quotes_found: int | None = None
    quotes_total: int | None = None
    # Показывается один раз — при создании или повторной выдаче ссылки.
    link: str | None = None


class ConsentDocumentOut(BaseModel):
    slug: str
    title: str
    version: str
    hash: str
    required: bool
    checkbox_label: str | None


class InvitationPublicOut(BaseModel):
    """Что видит кандидат по ссылке до и после согласий."""

    status: InterviewStatusLiteral
    organization_name: str
    vacancy_title: str
    intro_text: str
    question_count: int
    estimated_minutes: int
    prep_seconds: int
    max_answer_seconds: int
    retakes_allowed: int
    practice_question_enabled: bool
    # live — живой диалог, push_to_talk — кнопки записи; кандидат видит правила до старта.
    interview_mode: str = "live"
    expires_at: datetime
    needs_consent: bool
    candidate_full_name: str
    candidate_email: EmailStr
    consent_documents: list[ConsentDocumentOut]
    current_question_index: int


class ConsentSubmit(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    personal_data_accepted: bool
    privacy_policy_accepted: bool
    newsletter_accepted: bool = False
    # Версии документов, которые кандидат видел; сверяются с текущими.
    document_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("full_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()
