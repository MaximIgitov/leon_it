"""Запуск кода кандидата: задел за фиче-флагом.

Секция кода в комнате работает без раннера: кандидат пишет и отправляет код,
он сохраняется в ответе (``Answer.code_submission``) и попадает в отчёт и к
оценщику. Кнопка «Запустить» появляется, когда ``CODE_RUNNER`` указывает на
реальную реализацию протокола ``CodeRunner``.

План песочницы (не реализовано, см. ``registry.py``): изолированный запуск
в docker/firecracker с лимитами CPU, памяти, сети и времени, либо внешний
сервис вроде Piston / Judge0 — оба варианта укладываются в тот же протокол.
"""

from leonit.code_runner.base import (
    CodeRunner,
    NullCodeRunner,
    RunnerDisabled,
    RunResult,
    RunStatus,
    SourceTooLargeError,
)
from leonit.code_runner.registry import get_code_runner, register_code_runner

__all__ = [
    "CodeRunner",
    "NullCodeRunner",
    "RunResult",
    "RunStatus",
    "RunnerDisabled",
    "SourceTooLargeError",
    "get_code_runner",
    "register_code_runner",
]
