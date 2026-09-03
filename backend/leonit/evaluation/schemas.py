"""Схемы заключения и API оценки.

Модели structured output описаны по-русски намеренно: ``model_json_schema`` со
всеми ``description`` уходит в промпт, и именно эти описания объясняют модели,
что положить в каждое поле. Числовые границы (баллы 1–4, confidence 0..1, длина
цитаты) тоже живут здесь: pydantic отвергает ответ вне границ, и модель получает
шанс исправиться через repair-раунд ``complete_structured``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Recommendation = Literal["fit", "no_fit", "needs_check"]
RECOMMENDATIONS: tuple[Recommendation, ...] = ("fit", "no_fit", "needs_check")
EvaluationStatusLiteral = Literal["pending", "done", "failed"]
SkillLevel = Literal["упоминает", "применял", "уверенно", "эксперт"]

QUOTE_MAX_CHARS = 300


# --------------------------------------------------------- structured output


class Evidence(BaseModel):
    """Цитата из транскрипта, на которую опирается утверждение."""

    answer_id: str = Field(
        description="Идентификатор ответа (answer_id из заголовка секции транскрипта)"
    )
    question_index: int = Field(
        ge=0, description="Номер вопроса, начиная с нуля (как в заголовке секции)"
    )
    quote: str = Field(
        min_length=1,
        max_length=QUOTE_MAX_CHARS,
        description=(
            "Дословная цитата из транскрипта без правок и пересказа, не длиннее "
            f"{QUOTE_MAX_CHARS} символов"
        ),
    )
    start_s: float | None = Field(
        default=None, ge=0, description="Начало цитаты в секундах от начала ответа, если известно"
    )
    end_s: float | None = Field(
        default=None, ge=0, description="Конец цитаты в секундах от начала ответа, если известно"
    )


class CompetencyScore(BaseModel):
    competency_id: str = Field(description="Идентификатор компетенции из рубрики вакансии")
    name: str = Field(description="Название компетенции, как в рубрике")
    score: int = Field(
        ge=1, le=4, description="Балл по якорным уровням рубрики: строго целое от 1 до 4"
    )
    rationale: str = Field(
        description="Обоснование балла: что именно в ответах соответствует выбранному уровню"
    )
    evidence: list[Evidence] = Field(
        default_factory=list, description="Цитаты, подтверждающие балл (1–3 на компетенцию)"
    )


class QuestionAssessment(BaseModel):
    question_index: int = Field(ge=0, description="Номер вопроса, начиная с нуля")
    answer_id: str | None = Field(
        default=None, description="Идентификатор оценённого ответа; null, если транскрипта нет"
    )
    score: int = Field(ge=1, le=4, description="Качество ответа на вопрос: целое от 1 до 4")
    covered_points: list[str] = Field(
        default_factory=list,
        description="Какие из ожидаемых пунктов ответа кандидат раскрыл",
    )
    missed_points: list[str] = Field(
        default_factory=list,
        description="Какие ожидаемые пункты кандидат не затронул или раскрыл неверно",
    )
    comment: str = Field(description="Короткий комментарий к ответу (1–3 предложения)")
    evidence: list[Evidence] = Field(
        default_factory=list, description="Цитаты из этого ответа, подтверждающие оценку"
    )


class SkillDetected(BaseModel):
    name: str = Field(description="Технология, инструмент или практика, упомянутая кандидатом")
    level: SkillLevel = Field(
        description=(
            "Глубина владения по ответам: «упоминает» — назвал без деталей; «применял» — "
            "описал реальный опыт; «уверенно» — объяснил устройство и компромиссы; "
            "«эксперт» — глубокие детали, ограничения, альтернативы"
        )
    )
    evidence: list[Evidence] = Field(
        default_factory=list, description="Цитаты, из которых виден уровень владения"
    )


class EvaluationOutput(BaseModel):
    """Заключение оценщика. Рекомендацию система вычисляет сама — модель её не даёт."""

    summary: str = Field(
        description="Резюме по кандидату: 3–5 предложений о соответствии требованиям вакансии"
    )
    competency_scores: list[CompetencyScore] = Field(
        default_factory=list,
        description="Балл по каждой компетенции рубрики (все компетенции, без пропусков)",
    )
    question_assessments: list[QuestionAssessment] = Field(
        default_factory=list, description="Оценка каждого вопроса интервью по порядку"
    )
    strengths: list[str] = Field(
        default_factory=list, description="Сильные стороны, подтверждённые ответами"
    )
    growth_areas: list[str] = Field(
        default_factory=list, description="Зоны роста: чего не хватило или что раскрыто слабо"
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Риски для найма на эту позицию (несоответствие уровню, пробелы)",
    )
    skills: list[SkillDetected] = Field(
        default_factory=list, description="Навыки, обнаруженные в ответах, с уровнем владения"
    )
    follow_up_checks: list[str] = Field(
        default_factory=list,
        description="Что стоит уточнить на живом созвоне: конкретные вопросы или темы",
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Только факты из ответов, которые должны насторожить (противоречия, "
            "признание в подмене опыта); не домыслы"
        ),
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Уверенность в заключении от 0 до 1: ниже 0.4 при неполных, коротких или "
            "отсутствующих транскриптах"
        ),
    )
    transcript_quality_note: str | None = Field(
        default=None,
        description=(
            "Пометка о качестве транскриптов: обрывы, недоступные ответы, шум; null, "
            "если всё в порядке"
        ),
    )


class CandidateFeedback(BaseModel):
    """Нейтральная обратная связь кандидату: без баллов, рекомендации и integrity."""

    greeting: str = Field(description="Обращение к кандидату на «вы», без имени")
    strengths: list[str] = Field(
        min_length=1,
        max_length=3,
        description="2–3 сильные стороны, которые проявились в ответах",
    )
    suggestions: list[str] = Field(
        min_length=1,
        max_length=4,
        description="2–4 конкретных совета, что подтянуть или как лучше раскрывать ответы",
    )
    closing: str = Field(description="Короткое доброжелательное завершение")


# ------------------------------------------------------------ входные данные


class RubricLevelSet(BaseModel):
    """Компетенция рубрики в том виде, в каком она уходит в промпт."""

    id: str
    name: str
    description: str = ""
    weight: int = Field(default=3, ge=1, le=5)
    levels: dict[str, str] = Field(default_factory=dict)


class VacancyContext(BaseModel):
    title: str
    description: str = ""
    requirements: str = ""
    skills: list[str] = Field(default_factory=list)
    level: str | None = None
    rubric: list[RubricLevelSet] = Field(default_factory=list)


class QuestionContext(BaseModel):
    index: int = Field(ge=0)
    id: str | None = None
    text: str
    expected_points: list[str] = Field(default_factory=list)
    competency_ids: list[str] = Field(default_factory=list)


class TranscriptSegmentContext(BaseModel):
    start_s: float
    end_s: float
    text: str


class TranscriptContext(BaseModel):
    """Транскрипт одного ответа или причина его отсутствия."""

    question_index: int = Field(ge=0)
    answer_id: str | None = None
    # done — есть текст; иначе в промпт уходит пометка «транскрипт недоступен».
    status: str = "done"
    text: str | None = None
    segments: list[TranscriptSegmentContext] = Field(default_factory=list)
    duration_s: float | None = None

    @property
    def available(self) -> bool:
        return self.status == "done" and bool((self.text or "").strip())


# --------------------------------------------------------------------- API


class EvaluationOut(BaseModel):
    interview_id: str
    status: EvaluationStatusLiteral
    fit_score: float | None
    recommendation: Recommendation | None
    output: EvaluationOutput | None
    candidate_feedback: CandidateFeedback | None
    model: str
    prompt_version: str
    evaluated_at: datetime | None
    error: str | None


class ReprocessAccepted(BaseModel):
    interview_id: str
    job_id: str
    status: str


class RankingItem(BaseModel):
    interview_id: str
    candidate_id: str
    candidate_name: str
    candidate_email: str
    status: str
    fit_score: float | None
    recommendation: Recommendation | None
    evaluated_at: datetime | None
    decision: str | None
    completed_at: datetime | None


def output_to_dict(output: EvaluationOutput) -> dict[str, Any]:
    return output.model_dump(mode="json")
