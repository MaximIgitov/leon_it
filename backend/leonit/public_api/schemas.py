"""Схемы публичного API v1.

Отдельные от внутренних схем кабинета: публичный контракт версионируется и
документируется, а кабинет может меняться свободно. Описания полей попадают в
OpenAPI и страницу документации.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from leonit.candidates.schemas import InterviewStatusLiteral, SourceLiteral
from leonit.vacancies.schemas import (
    InterviewSettings,
    LevelLiteral,
    QuestionOut,
    RubricCompetency,
    VacancyStatusLiteral,
)

Recommendation = Literal["fit", "no_fit", "needs_check"]
Decision = Literal["advance", "reject", "hold"]


class ApiVacancy(BaseModel):
    model_config = ConfigDict(title="Vacancy")

    id: str = Field(description="Идентификатор вакансии (UUID).")
    title: str
    status: VacancyStatusLiteral = Field(
        description="draft — черновик, published — принимает кандидатов, archived — в архиве."
    )
    level: LevelLiteral | None = Field(description="Ожидаемый уровень кандидата.")
    skills: list[str]
    question_count: int = Field(description="Сколько вопросов задаётся на интервью.")
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class ApiVacancyDetail(ApiVacancy):
    model_config = ConfigDict(title="VacancyDetail")

    description: str
    requirements: str
    language: str = Field(description="Язык интервью (ISO 639-1).")
    rubric: list[RubricCompetency] = Field(
        description="Рубрика компетенций с якорными уровнями 1–4."
    )
    settings: InterviewSettings = Field(description="Тайминги, перезаписи, озвучка, срок ссылки.")
    questions: list[QuestionOut]


class ApiCandidate(BaseModel):
    model_config = ConfigDict(title="Candidate")

    id: str = Field(description="Идентификатор кандидата (UUID).")
    full_name: str
    email: EmailStr
    phone: str | None
    source: SourceLiteral = Field(description="Откуда пришёл кандидат; через API — `api`.")
    notes: str
    external_ref: str | None = Field(description="Ваш идентификатор кандидата (ATS, HH).")
    created_at: datetime
    interview_count: int
    last_interview_status: InterviewStatusLiteral | None


class ApiInviteRequest(BaseModel):
    model_config = ConfigDict(title="InviteRequest")

    vacancy_id: UUID = Field(
        description=(
            "Опубликованная вакансия (UUID). Неверный формат — 422, чужая или несуществующая — 404."
        )
    )
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr = Field(
        description="Кандидат находится по e-mail; если уже есть — используется существующий."
    )
    send_email: bool = Field(
        default=True, description="Отправить письмо с приглашением. Ссылка всё равно в ответе."
    )


class ApiInterview(BaseModel):
    model_config = ConfigDict(title="Interview")

    id: str = Field(description="Идентификатор интервью (UUID).")
    status: InterviewStatusLiteral = Field(
        description=(
            "invited → opened → consented → in_progress → completed → processing → "
            "evaluated → reviewed / advanced / rejected; expired и cancelled — терминальные."
        )
    )
    vacancy_id: str
    vacancy_title: str
    candidate_id: str
    candidate_name: str
    candidate_email: EmailStr
    invited_at: datetime
    expires_at: datetime = Field(description="До какого момента действует ссылка кандидата.")
    opened_at: datetime | None
    consented_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    evaluated_at: datetime | None
    decided_at: datetime | None
    decision: Decision | None = Field(description="Решение человека — отдельно от рекомендации ИИ.")
    question_count: int | None = Field(description="Число вопросов; известно после старта.")
    fit_score: float | None = Field(
        description="Соответствие 0–100 по заключению модели; null, пока оценки нет."
    )
    recommendation: Recommendation | None = Field(
        description="Рекомендация ИИ: fit, no_fit или needs_check. Не заменяет решение."
    )
    link: str | None = Field(
        default=None,
        description="Ссылка для кандидата. Выдаётся один раз — в ответе на приглашение.",
    )


class ApiEvaluation(BaseModel):
    model_config = ConfigDict(title="Evaluation")

    status: str
    fit_score: float | None
    recommendation: Recommendation | None
    output: dict[str, Any] | None = Field(
        description="Структурированное заключение: саммари, баллы по компетенциям с цитатами."
    )
    evaluated_at: datetime | None


class ApiReportAnswer(BaseModel):
    model_config = ConfigDict(title="ReportAnswer")

    id: str
    question_index: int
    question_text: str | None
    attempt: int = Field(description="Номер попытки; в отчёт попадает последняя завершённая.")
    duration_ms: int | None
    status: str = Field(description="uploaded / processing / done / failed.")
    transcript_text: str | None
    transcript_segments: list[dict[str, Any]] | None = Field(
        description="Фрагменты транскрипта с таймкодами start_s / end_s."
    )
    media_url: str | None = Field(
        description=(
            "Подписанная ссылка на запись, действует 15 минут. Только с областью media:read; "
            "иначе null."
        )
    )
    media_content_type: str | None


class ApiInterviewReport(BaseModel):
    model_config = ConfigDict(title="InterviewReport")

    interview: ApiInterview
    decision_note: str | None
    evaluation: ApiEvaluation | None = Field(
        description="null, пока модуль оценки не обработал интервью."
    )
    answers: list[ApiReportAnswer]
    media_urls_included: bool = Field(
        description="Есть ли у токена область media:read (без неё media_url всегда null)."
    )


class ApiRankingRow(BaseModel):
    model_config = ConfigDict(title="RankingRow")

    position: int = Field(description="Место в рейтинге, начиная с 1.")
    interview_id: str
    candidate_id: str
    candidate_name: str
    candidate_email: EmailStr
    status: InterviewStatusLiteral
    fit_score: float | None
    recommendation: Recommendation | None
    evaluated_at: datetime | None
    decision: Decision | None
    completed_at: datetime | None
