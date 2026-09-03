"""Детерминированная рекомендация по баллам.

Модель ставит баллы и обосновывает их цитатами, но «подходит / не подходит /
нужна проверка» выводится здесь, а не моделью: два кандидата с одинаковыми
баллами гарантированно получают одинаковую рекомендацию, а логика порогов
прозрачна и проверяется тестами на граничные значения. Пороги
``EVAL_FIT_THRESHOLD``/``EVAL_NO_FIT_THRESHOLD`` применяются в момент оценки и
сохраняются вместе с заключением: смена порогов действует на новые оценки, для
старых нужна переобработка (кнопка «Переобработать»). Веса берутся из текущей
рубрики вакансии на момент оценки. Функции чистые — их гоняет и eval-скрипт, и
тесты.

Полнота: балл считается по компетенциям рубрики, а не по тому, что вернула
модель. Пропущенная компетенция считается как 1 (нет подтверждения — нет
балла) и не даёт «fit»; выдуманные компетенции вне рубрики в среднее не
входят; дубли по ``competency_id`` учитываются один раз.
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
# Вес компетенции по умолчанию совпадает с RubricCompetency.weight.
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


@dataclass(frozen=True, slots=True)
class RubricCoverage:
    """Сверка баллов модели с рубрикой: что учтено, что пропущено, что лишнее."""

    # (id компетенции из рубрики, балл, вес) — по одному на компетенцию рубрики.
    scored: list[tuple[str, int, int]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)

    @property
    def unmatched(self) -> bool:
        """Модель не назвала ни одной компетенции рубрики (баллы есть, но не привязаны)."""
        return bool(self.ignored) and len(self.missing) == len(self.scored)


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


def _rubric_ids(rubric: Iterable[Mapping[str, Any]] | None) -> dict[str, str]:
    """Сопоставление «id или имя в нижнем регистре → id компетенции рубрики»."""
    mapping: dict[str, str] = {}
    for item in rubric or ():
        item_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip().lower()
        if not item_id:
            continue
        mapping[item_id] = item_id
        if name:
            mapping.setdefault(name, item_id)
    return mapping


def _weight_of(score: CompetencyScore, weights: Mapping[str, int]) -> int:
    if score.competency_id in weights:
        return weights[score.competency_id]
    return weights.get(score.name.strip().lower(), DEFAULT_WEIGHT)


def _rubric_id_of(score: CompetencyScore, ids: Mapping[str, str]) -> str | None:
    if score.competency_id in ids:
        return ids[score.competency_id]
    return ids.get(score.name.strip().lower())


def rubric_coverage(
    competency_scores: Iterable[CompetencyScore], rubric: Iterable[Mapping[str, Any]] | None
) -> RubricCoverage:
    """Разложить баллы модели по компетенциям рубрики."""
    rubric_list = list(rubric or ())
    ids = _rubric_ids(rubric_list)
    weights = rubric_weights(rubric_list)
    by_id: dict[str, int] = {}
    duplicates: list[str] = []
    ignored: list[str] = []
    for item in competency_scores:
        rubric_id = _rubric_id_of(item, ids)
        if rubric_id is None:
            ignored.append(item.competency_id or item.name)
            continue
        if rubric_id in by_id:
            duplicates.append(rubric_id)
            continue
        by_id[rubric_id] = int(item.score)
    scored: list[tuple[str, int, int]] = []
    missing: list[str] = []
    for item in rubric_list:
        rubric_id = str(item.get("id") or "").strip()
        if not rubric_id:
            continue
        weight = weights.get(rubric_id, DEFAULT_WEIGHT)
        if rubric_id in by_id:
            scored.append((rubric_id, by_id[rubric_id], weight))
        else:
            missing.append(rubric_id)
            scored.append((rubric_id, SCALE_MIN, weight))
    return RubricCoverage(scored=scored, missing=missing, ignored=ignored, duplicates=duplicates)


def normalize(average: float) -> float:
    """Средний балл 1..4 → 0..100: 1 → 0, 4 → 100."""
    clipped = min(max(average, SCALE_MIN), SCALE_MAX)
    return round((clipped - SCALE_MIN) / (SCALE_MAX - SCALE_MIN) * 100, 1)


def fit_score(
    competency_scores: list[CompetencyScore],
    rubric: Iterable[Mapping[str, Any]] | None,
    question_assessments: list[QuestionAssessment] | None = None,
) -> float | None:
    """Взвешенное среднее по компетенциям рубрики (веса из рубрики); без рубрики —
    среднее по вопросам. None — оценивать нечего."""
    rubric_list = list(rubric or ())
    if rubric_list and competency_scores:
        coverage = rubric_coverage(competency_scores, rubric_list)
        if coverage.unmatched:
            # Баллы вообще не привязаны к рубрике: считаем простое среднее, а
            # recommend() не даст «fit» и объяснит почему.
            return normalize(sum(item.score for item in competency_scores) / len(competency_scores))
        total = sum(weight for _, _, weight in coverage.scored)
        if total > 0:
            weighted = sum(score * weight for _, score, weight in coverage.scored)
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
    """Рекомендация по порогам с ограничениями: единица по критичной компетенции,
    пропущенная компетенция рубрики и низкая уверенность не дают «fit»."""
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

    rubric_list = list(rubric or ())
    weights = rubric_weights(rubric_list)
    for item in competency_scores or ():
        if item.score == SCALE_MIN and _weight_of(item, weights) >= CRITICAL_WEIGHT:
            reasons.append(f"балл 1 по критичной компетенции «{item.name}»")
            if recommendation == "fit":
                recommendation = "needs_check"

    if rubric_list and competency_scores:
        coverage = rubric_coverage(competency_scores, rubric_list)
        if coverage.unmatched:
            reasons.append("баллы не привязаны к компетенциям рубрики")
            if recommendation == "fit":
                recommendation = "needs_check"
        elif coverage.missing:
            reasons.append("нет балла по компетенциям: " + ", ".join(coverage.missing))
            if recommendation == "fit":
                recommendation = "needs_check"
        if coverage.ignored:
            reasons.append("вне рубрики, не учтено: " + ", ".join(coverage.ignored))
        if coverage.duplicates:
            reasons.append("повторы баллов учтены один раз: " + ", ".join(coverage.duplicates))

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
