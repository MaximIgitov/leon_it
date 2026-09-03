"""Протокол раннера кода, результат запуска и заглушка по умолчанию."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from fastapi import status

from leonit.core.errors import ConflictError, DomainError

RunStatus = Literal["ok", "error", "timeout"]


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunnerDisabled(ConflictError):
    """Раннер не настроен: наружу — 409 с кодом ``runner_disabled``."""

    code = "runner_disabled"

    def __init__(self, detail: str = "Запуск кода пока недоступен: раннер не настроен") -> None:
        super().__init__(detail)


class SourceTooLargeError(DomainError):
    """Исходник больше ``CODE_MAX_SOURCE_BYTES``."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE


@runtime_checkable
class CodeRunner(Protocol):
    """Изолированный запуск исходника.

    Реализация отвечает за песочницу (лимиты CPU/памяти/сети/времени) и обязана
    вернуть ``RunResult`` даже при таймауте (``status="timeout"``), а не бросать
    исключение — кандидат должен увидеть «превышено время», а не 500.
    """

    name: str
    enabled: bool

    async def run(
        self, language: str, source: str, stdin: str = "", timeout_s: float = 10.0
    ) -> RunResult: ...


class NullCodeRunner:
    """Раннер по умолчанию: запуск выключен."""

    name = "none"
    enabled = False

    async def run(
        self, language: str, source: str, stdin: str = "", timeout_s: float = 10.0
    ) -> RunResult:
        raise RunnerDisabled()
