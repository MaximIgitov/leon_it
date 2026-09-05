from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

VacancyStatusLiteral = Literal["draft", "published", "archived"]
QuestionKindLiteral = Literal["video", "code"]
FeedbackModeLiteral = Literal["off", "after_decision", "auto_after_days"]
LevelLiteral = Literal["intern", "junior", "middle", "senior", "lead"]

RUBRIC_LEVELS = ("1", "2", "3", "4")


class RubricCompetency(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    weight: int = Field(default=3, ge=1, le=5)
    # Якорные уровни 1–4: что именно означает каждый балл для этой компетенции.
    levels: dict[str, str] = Field(default_factory=dict)

    @field_validator("levels")
    @classmethod
    def _only_known_levels(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - set(RUBRIC_LEVELS)
        if unknown:
            raise ValueError(f"Допустимые уровни: {', '.join(RUBRIC_LEVELS)}")
        return {key: text.strip() for key, text in value.items()}


class InterviewSettings(BaseModel):
    intro_text: str = Field(default="", max_length=4000)
    prep_seconds: int = Field(default=30, ge=0, le=600)
    max_answer_seconds: int = Field(default=180, ge=30, le=900)
    retakes_allowed: int = Field(default=1, ge=0, le=5)
    practice_question_enabled: bool = True
    followups_enabled: bool = False
    followups_max: int = Field(default=1, ge=0, le=3)
    tts_enabled: bool = True
    voice: str = Field(default="nova", max_length=64)
    # Видео с ИИ-интервьюером вместо озвучки; работает, если на сервере настроен провайдер.
    avatar_enabled: bool = False
    invitation_days: int = Field(default=7, ge=1, le=60)
    candidate_feedback_mode: FeedbackModeLiteral = "after_decision"
    candidate_feedback_after_days: int = Field(default=3, ge=1, le=30)


class VacancyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=20000)
    requirements: str = Field(default="", max_length=20000)
    skills: list[str] = Field(default_factory=list, max_length=50)
    level: LevelLiteral | None = None

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            item = item.strip()
            if item and item.lower() not in {s.lower() for s in seen}:
                seen.append(item[:64])
        return seen


class VacancyUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    requirements: str | None = Field(default=None, max_length=20000)
    skills: list[str] | None = Field(default=None, max_length=50)
    level: LevelLiteral | None = None
    rubric: list[RubricCompetency] | None = Field(default=None, max_length=20)
    settings: InterviewSettings | None = None

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return VacancyCreate(title="x", skills=value).skills

    @field_validator("rubric")
    @classmethod
    def _unique_competency_ids(cls, value: list[RubricCompetency] | None):
        if value is not None:
            ids = [item.id for item in value]
            if len(ids) != len(set(ids)):
                raise ValueError("Идентификаторы компетенций должны быть уникальны")
        return value


class QuestionIn(BaseModel):
    id: str | None = None
    kind: QuestionKindLiteral = "video"
    text: str = Field(min_length=1, max_length=4000)
    expected_points: list[str] = Field(default_factory=list, max_length=20)
    competency_ids: list[str] = Field(default_factory=list, max_length=20)
    allows_followup: bool = False
    prep_seconds: int | None = Field(default=None, ge=0, le=600)
    max_answer_seconds: int | None = Field(default=None, ge=30, le=900)
    retakes_allowed: int | None = Field(default=None, ge=0, le=5)

    @field_validator("expected_points")
    @classmethod
    def _clean_points(cls, value: list[str]) -> list[str]:
        return [item.strip()[:500] for item in value if item.strip()]


class QuestionsReplace(BaseModel):
    questions: list[QuestionIn] = Field(max_length=40)

    @model_validator(mode="after")
    def _ids_unique(self):
        ids = [q.id for q in self.questions if q.id]
        if len(ids) != len(set(ids)):
            raise ValueError("Дублирующиеся идентификаторы вопросов")
        return self


class QuestionOut(BaseModel):
    id: str
    position: int
    kind: QuestionKindLiteral
    text: str
    expected_points: list[str]
    competency_ids: list[str]
    allows_followup: bool
    prep_seconds: int | None
    max_answer_seconds: int | None
    retakes_allowed: int | None


class VacancyOut(BaseModel):
    id: str
    title: str
    description: str
    requirements: str
    skills: list[str]
    level: LevelLiteral | None
    language: str
    status: VacancyStatusLiteral
    rubric: list[RubricCompetency]
    settings: InterviewSettings
    question_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    archived_at: datetime | None


class VacancyDetailOut(VacancyOut):
    questions: list[QuestionOut]
    # Настроен ли на сервере провайдер аватара: без него переключатель в настройках неактивен.
    avatar_available: bool = False


class VacancyListItem(BaseModel):
    id: str
    title: str
    status: VacancyStatusLiteral
    level: LevelLiteral | None
    skills: list[str]
    question_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
