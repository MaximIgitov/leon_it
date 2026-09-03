from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from leonit.interviews.schemas import CodeSubmissionOut

Decision = Literal["advance", "reject", "hold"]


class DecisionIn(BaseModel):
    decision: Decision
    note: str = Field(default="", max_length=4000)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    answer_id: str | None = None
    at_s: float | None = Field(default=None, ge=0)


class NoteOut(BaseModel):
    id: str
    author_user_id: str | None
    author_label: str
    text: str
    answer_id: str | None
    at_s: float | None
    created_at: datetime


class ShareCreate(BaseModel):
    label: str = Field(default="", max_length=255)
    expires_in_days: int = Field(default=14, ge=1, le=90)
    include_integrity: bool = False
    allow_download: bool = False


class ShareOut(BaseModel):
    id: str
    label: str
    expires_at: datetime
    revoked_at: datetime | None
    include_integrity: bool
    allow_download: bool
    view_count: int
    last_viewed_at: datetime | None
    created_at: datetime
    status: Literal["active", "expired", "revoked"]
    url: str | None = None


class ShareViewOut(BaseModel):
    what: str
    ip: str | None
    user_agent: str | None
    created_at: datetime


class PublicReportAnswer(BaseModel):
    id: str
    question_index: int
    question_text: str | None
    attempt: int
    duration_ms: int | None
    media_url: str | None
    media_content_type: str | None
    transcript_text: str | None
    transcript_segments: list[dict[str, Any]] | None
    status: str
    code_submission: CodeSubmissionOut | None = None


class PublicReport(BaseModel):
    """Отчёт по ссылке: один кандидат, без других кандидатов и (по умолчанию) integrity."""

    organization_name: str
    vacancy_title: str
    candidate_name: str
    candidate_email: str | None
    status: str
    completed_at: datetime | None
    decision: str | None
    decision_note: str | None
    evaluation: dict[str, Any] | None
    answers: list[PublicReportAnswer]
    notes: list[NoteOut]
    can_decide: bool
    can_note: bool
    integrity: dict[str, Any] | None
    expires_at: datetime
