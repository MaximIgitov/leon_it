"""Детерминированная рекомендация по баллам.

Модель ставит баллы и обосновывает их цитатами, но «подходит / не подходит /
нужна проверка» выводится здесь, а не моделью: так пороги можно менять без
переоценки, а два кандидата с одинаковыми баллами гарантированно получают
одинаковую рекомендацию. Функции чистые — их гоняет и eval-скрипт, и тесты на
граничные значения.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from leonit.evaluation.schemas import (
    CompetencyScore,
    EvaluationOutput,
    QuestionAssessment,
    Recommendation,
)

SCALE_MIN = 1
SCALE_MAX = 4
# Вес компетенции по умолчанию совпадает с RubricCompetency.weight: так балл по
# компетенции, которую модель назвала не по id рубрики, не выпадает из среднего.
DEFAULT_WEIGHT = 3
# Компетенции с таким весом считаются критичными: единица по ним блокирует «fit».
CRITICAL_WEIGHT = 4
LOW_CONFIDENCE = 0.4


@dataclass(frozen=True, slots=True)
class Thresholds:
    fit: float = 70.0
    no_fit: float = 45.0

    def __post_init__(self) -> None:
        if not 0 <= self.no_fit < self.fit <= 100:
            raise ValueError(
                f"thresholds must satisfy 0 <= no_fit < fit <= 100, got {self.no_fit}/{self.fit}"
            )


@dataclass(frozen=True, slots=True)
class ScoringResult:
    fit_score: float | None
    recommendation: Recommendation
    # Почему рекомендация именно такая (пороги, ограничения) — для отчёта и логов.
    reasons: list[str] = field(default_factory=list)


def rubric_weights(rubric: Iterable[Mapping[str, Any]] | None) -> dict[str, int]:
    """Вес компетенции по id (и по имени в нижнем регистре — на случай, если модель
    назвала компетенцию по названию)."""
    weights: dict[str, int] = {}
    for item in rubric or ():
        try:
            weight = int(item.get("weight", DEFAULT_WEIGHT))
        except (TypeError, ValueError):
            weight = DEFAULT_WEIGHT
        weight = max(1, min(5, weight))
        if item.get("id"):
            weights[str(item["id"])] = weight
        if item.get("name"):
            weights.setdefault(str(item["name"]).strip().lower(), weight)
    return weights


def _weight_of(score: CompetencyScore, weights: Mapping[str, int]) -> int:
    if score.competency_id in weights:
        return weights[score.competency_id]
    return weights.get(score.name.strip().lower(), DEFAULT_WEIGHT)


def normalize(average: float) -> float:
    """Средний балл 1..4 → 0..100: 1 → 0, 4 → 100."""
    clipped = min(max(average, SCALE_MIN), SCALE_MAX)
    return round((clipped - SCALE_MIN) / (SCALE_MAX - SCALE_MIN) * 100, 1)


def fit_score(
    competency_scores: list[CompetencyScore],
    rubric: Iterable[Mapping[str, Any]] | None,
    question_assessments: list[QuestionAssessment] | None = None,
) -> float | None:
    """Взвешенное среднее по компетенциям (веса из рубрики); без рубрики —
    среднее по вопросам. None — оценивать нечего."""
    weights = rubric_weights(rubric)
    if weights and competency_scores:
        total = sum(_weight_of(item, weights) for item in competency_scores)
        if total > 0:
            weighted = sum(item.score * _weight_of(item, weights) for item in competency_scores)
            return normalize(weighted / total)
    if question_assessments:
        return normalize(
            sum(item.score for item in question_assessments) / len(question_assessments)
        )
    if competency_scores:
        # Рубрики нет, но модель всё же оценила компетенции: простое среднее.
        return normalize(sum(item.score for item in competency_scores) / len(competency_scores))
    return None


def recommend(
    score: float | None,
    *,
    competency_scores: list[CompetencyScore] | None = None,
    rubric: Iterable[Mapping[str, Any]] | None = None,
    confidence: float | None = None,
    thresholds: Thresholds | None = None,
) -> ScoringResult:
    """Рекомендация по порогам с двумя ограничениями: единица по критичной
    компетенции и низкая уверенность не дают «fit»."""
    thresholds = thresholds or Thresholds()
    reasons: list[str] = []
    if score is None:
        return ScoringResult(None, "needs_check", ["нет баллов для расчёта"])

    if score >= thresholds.fit:
        recommendation: Recommendation = "fit"
        reasons.append(f"fit_score {score} ≥ порога {thresholds.fit:g}")
    elif score < thresholds.no_fit:
        recommendation = "no_fit"
        reasons.append(f"fit_score {score} < порога {thresholds.no_fit:g}")
    else:
        recommendation = "needs_check"
        reasons.append(
            f"fit_score {score} между порогами {thresholds.no_fit:g} и {thresholds.fit:g}"
        )

    weights = rubric_weights(rubric)
    for item in competency_scores or ():
        if item.score == SCALE_MIN and _weight_of(item, weights) >= CRITICAL_WEIGHT:
            reasons.append(f"балл 1 по критичной компетенции «{item.name}»")
            if recommendation == "fit":
                recommendation = "needs_check"

    if confidence is not None and confidence < LOW_CONFIDENCE:
        reasons.append(f"уверенность модели {confidence:.2f} ниже {LOW_CONFIDENCE}")
        recommendation = "needs_check"

    return ScoringResult(score, recommendation, reasons)


def score_output(
    output: EvaluationOutput,
    rubric: Iterable[Mapping[str, Any]] | None,
    *,
    thresholds: Thresholds | None = None,
) -> ScoringResult:
    """Полный расчёт по заключению модели: балл и рекомендация."""
    rubric_list = list(rubric or ())
    score = fit_score(output.competency_scores, rubric_list, output.question_assessments)
    return recommend(
        score,
        competency_scores=output.competency_scores,
        rubric=rubric_list,
        confidence=output.confidence,
        thresholds=thresholds,
    )
