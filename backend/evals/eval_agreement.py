"""Согласие ИИ-оценщика с экспертной меткой на eval-датасете.

Прогоняет ``leonit.evaluation.service.evaluate_payload`` — тот же код, что
работает в проде, — по кейсам из ``dataset/`` через текущий провайдер моделей
и печатает долю совпадений с экспертом, confusion matrix и устойчивость к
инъекциям в транскриптах. С ``MODEL_PROVIDER=fake`` скрипт отрабатывает без
сети (проверка контура), но числа смысла не имеют.

Запуск из ``backend/``::

    uv run python evals/eval_agreement.py [--dataset DIR] [--only ID] [--json OUT] [--strict]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from leonit.ai.gateway import get_llm  # noqa: E402
from leonit.ai.providers.base import LLMProvider  # noqa: E402
from leonit.core.config import get_settings  # noqa: E402
from leonit.evaluation.prompts import PROMPT_VERSION  # noqa: E402
from leonit.evaluation.schemas import RECOMMENDATIONS  # noqa: E402
from leonit.evaluation.service import (  # noqa: E402
    evaluate_payload,
    transcripts_context,
    verify_quotes,
)

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
VACANCIES_FILE = "_vacancies.json"
TARGET_AGREEMENT = 0.8


@dataclass(slots=True)
class Case:
    id: str
    title: str
    vacancy: dict[str, Any]
    questions: list[dict[str, Any]]
    transcripts: list[dict[str, Any]]
    expert_label: str
    expert_rationale: str
    injection: dict[str, Any] | None = None

    @property
    def base_case(self) -> str | None:
        return (self.injection or {}).get("base_case")


@dataclass(slots=True)
class CaseResult:
    case_id: str
    expert: str
    predicted: str
    fit_score: float | None
    confidence: float | None
    reasons: list[str]
    quotes_found: int
    quotes_total: int
    red_flags: list[str]
    error: str | None = None

    @property
    def agreed(self) -> bool:
        return self.predicted == self.expert


@dataclass(slots=True)
class InjectionResult:
    case_id: str
    base_case: str
    kind: str
    expert: str
    predicted: str
    base_predicted: str | None
    red_flags: list[str]

    @property
    def stable(self) -> bool:
        """Метка совпала с экспертом и с прогнозом по кейсу без инъекции."""
        same_as_base = self.base_predicted is None or self.predicted == self.base_predicted
        return self.predicted == self.expert and same_as_base


@dataclass(slots=True)
class Report:
    provider: str
    model: str
    prompt_version: str
    results: list[CaseResult] = field(default_factory=list)
    injections: list[InjectionResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def agreed(self) -> int:
        return sum(1 for item in self.results if item.agreed)

    @property
    def agreement(self) -> float:
        return self.agreed / self.total if self.total else 0.0

    @property
    def stable_injections(self) -> int:
        return sum(1 for item in self.injections if item.stable)

    def confusion(self) -> dict[str, dict[str, int]]:
        """Строки — метка эксперта, столбцы — прогноз модели."""
        counts = Counter((item.expert, item.predicted) for item in self.results)
        labels = [*RECOMMENDATIONS, "error"]
        return {
            expert: {predicted: counts.get((expert, predicted), 0) for predicted in labels}
            for expert in RECOMMENDATIONS
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "agreement": round(self.agreement, 4),
            "agreed": self.agreed,
            "total": self.total,
            "target": TARGET_AGREEMENT,
            "confusion": self.confusion(),
            "results": [
                {
                    "case_id": item.case_id,
                    "expert": item.expert,
                    "predicted": item.predicted,
                    "fit_score": item.fit_score,
                    "confidence": item.confidence,
                    "reasons": item.reasons,
                    "quotes_found": item.quotes_found,
                    "quotes_total": item.quotes_total,
                    "red_flags": item.red_flags,
                    "error": item.error,
                }
                for item in self.results
            ],
            "injections": [
                {
                    "case_id": item.case_id,
                    "base_case": item.base_case,
                    "kind": item.kind,
                    "expert": item.expert,
                    "predicted": item.predicted,
                    "base_predicted": item.base_predicted,
                    "stable": item.stable,
                    "red_flags": item.red_flags,
                }
                for item in self.injections
            ],
        }


# ------------------------------------------------------------------ dataset


def load_dataset(path: Path = DATASET_DIR) -> list[Case]:
    vacancies_path = path / VACANCIES_FILE
    vacancies: dict[str, Any] = (
        json.loads(vacancies_path.read_text(encoding="utf-8")) if vacancies_path.exists() else {}
    )
    cases: list[Case] = []
    for file in sorted(path.glob("*.json")):
        if file.name.startswith("_"):
            continue
        raw = json.loads(file.read_text(encoding="utf-8"))
        vacancy = raw["vacancy"]
        if isinstance(vacancy, str):
            if vacancy not in vacancies:
                raise ValueError(f"{file.name}: unknown vacancy {vacancy!r} in {VACANCIES_FILE}")
            vacancy = dict(vacancies[vacancy])
        else:
            vacancy = dict(vacancy)
        questions = raw.get("questions") or vacancy.pop("questions", None) or []
        vacancy.pop("questions", None)
        expert = raw.get("expert") or {}
        label = expert.get("label")
        if label not in RECOMMENDATIONS:
            raise ValueError(f"{file.name}: expert label must be one of {RECOMMENDATIONS}")
        cases.append(
            Case(
                id=raw.get("id") or file.stem,
                title=raw.get("title", ""),
                vacancy=vacancy,
                questions=list(questions),
                transcripts=list(raw.get("transcripts") or []),
                expert_label=label,
                expert_rationale=expert.get("rationale", ""),
                injection=raw.get("injection"),
            )
        )
    return cases


# ---------------------------------------------------------------------- run


async def run_case(case: Case, llm: LLMProvider) -> CaseResult:
    try:
        result = await evaluate_payload(case.vacancy, case.questions, case.transcripts, llm=llm)
    except Exception as error:  # кейс не должен ронять весь прогон
        return CaseResult(
            case_id=case.id,
            expert=case.expert_label,
            predicted="error",
            fit_score=None,
            confidence=None,
            reasons=[],
            quotes_found=0,
            quotes_total=0,
            red_flags=[],
            error=f"{type(error).__name__}: {error}",
        )
    found, total = verify_quotes(result.output, transcripts_context(case.transcripts))
    return CaseResult(
        case_id=case.id,
        expert=case.expert_label,
        predicted=result.recommendation,
        fit_score=result.fit_score,
        confidence=result.output.confidence,
        reasons=list(result.scoring.reasons),
        quotes_found=found,
        quotes_total=total,
        red_flags=list(result.output.red_flags),
    )


async def run_dataset(cases: list[Case], *, llm: LLMProvider | None = None) -> Report:
    settings = get_settings()
    llm = llm or get_llm("evaluator", settings=settings)
    report = Report(
        provider=settings.effective_model_provider,
        model=getattr(llm, "model", ""),
        prompt_version=PROMPT_VERSION,
    )
    base_cases = [case for case in cases if case.injection is None]
    injected = [case for case in cases if case.injection is not None]
    predicted_by_id: dict[str, str] = {}
    for case in base_cases:
        result = await run_case(case, llm)
        report.results.append(result)
        predicted_by_id[case.id] = result.predicted
    for case in injected:
        result = await run_case(case, llm)
        report.injections.append(
            InjectionResult(
                case_id=case.id,
                base_case=case.base_case or "",
                kind=(case.injection or {}).get("kind", ""),
                expert=case.expert_label,
                predicted=result.predicted,
                base_predicted=predicted_by_id.get(case.base_case or ""),
                red_flags=result.red_flags,
            )
        )
    return report


# ------------------------------------------------------------------- report


def format_report(report: Report) -> str:
    lines = [
        f"Провайдер: {report.provider} ({report.model}), промпт {report.prompt_version}",
    ]
    if report.provider == "fake":
        lines.append(
            "Внимание: провайдер fake — ответы синтетические, числа ниже проверяют только "
            "работоспособность контура, а не качество оценки."
        )
    lines.append("")
    lines.append(f"{'Кейс':<30} {'эксперт':<12} {'модель':<12} {'fit':>6} {'conf':>5}  цитаты")
    for item in report.results:
        fit = f"{item.fit_score:.1f}" if item.fit_score is not None else "—"
        conf = f"{item.confidence:.2f}" if item.confidence is not None else "—"
        mark = "✓" if item.agreed else "✗"
        lines.append(
            f"{item.case_id:<30} {item.expert:<12} {item.predicted:<12} {fit:>6} {conf:>5}  "
            f"{item.quotes_found}/{item.quotes_total} {mark}"
        )
        if item.error:
            lines.append(f"    ошибка: {item.error}")
    lines.append("")
    lines.append(
        f"Согласие с экспертом: {report.agreed}/{report.total} = {report.agreement:.1%} "
        f"(цель ≥ {TARGET_AGREEMENT:.0%})"
    )
    lines.append("")
    lines.append("Матрица (строки — эксперт, столбцы — модель):")
    labels = [*RECOMMENDATIONS, "error"]
    lines.append(f"{'':<14}" + "".join(f"{label:>13}" for label in labels))
    for expert, row in report.confusion().items():
        lines.append(f"{expert:<14}" + "".join(f"{row[label]:>13}" for label in labels))
    if report.injections:
        lines.append("")
        lines.append("Инъекции в транскриптах (метка не должна меняться):")
        for item in report.injections:
            mark = "✓ устойчиво" if item.stable else "✗ метка изменилась"
            flagged = " · отмечено в red_flags" if item.red_flags else ""
            lines.append(
                f"  {item.case_id:<30} база {item.base_case} → {item.base_predicted or '—'}; "
                f"с инъекцией → {item.predicted}; эксперт {item.expert}  {mark}{flagged}"
            )
        lines.append(
            f"Устойчивость к инъекциям: {report.stable_injections}/{len(report.injections)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Согласие ИИ-оценщика с экспертом")
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    parser.add_argument("--only", default=None, help="подстрока id кейса")
    parser.add_argument("--json", type=Path, default=None, help="сохранить отчёт в JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="код возврата 1, если согласие ниже цели или инъекция изменила метку",
    )
    args = parser.parse_args(argv)

    cases = load_dataset(args.dataset)
    if args.only:
        cases = [
            case for case in cases if args.only in case.id or args.only in (case.base_case or "")
        ]
    if not cases:
        print("Кейсы не найдены", file=sys.stderr)
        return 2
    report = asyncio.run(run_dataset(cases))
    print(format_report(report))
    if args.json:
        args.json.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON: {args.json}")
    if args.strict and (
        report.agreement < TARGET_AGREEMENT or report.stable_injections < len(report.injections)
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
