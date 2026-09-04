"""Реестр моделей.

Модели лежат в пакетах предметных областей; Alembic и тесты импортируют их через
одну точку, чтобы метаданные были полными независимо от порядка импортов.
"""

from __future__ import annotations

import importlib

MODEL_MODULES: tuple[str, ...] = (
    "leonit.accounts.models",
    "leonit.vacancies.models",
    "leonit.jobs.models",
    "leonit.candidates.models",
    "leonit.notifications.models",
    "leonit.interviews.models",
    "leonit.reports.models",
    "leonit.assistant.models",
    "leonit.api_tokens.models",
    "leonit.evaluation.models",
    "leonit.integrity.models",
    "leonit.hh.models",
    "leonit.huntflow.models",
)


def load_all_models() -> None:
    for module in MODEL_MODULES:
        importlib.import_module(module)
