"""Секция кода в ответе: валидация, представление наружу, текст для оценщика.

Код хранится в ``Answer.code_submission`` как JSON
``{language, source, submitted_at, run_result}``. Ответ на вопрос ``kind=code``
считается данным после отправки кода (``submitted_at``); видео-пояснение к нему
опционально и живёт в той же попытке (``media_key``).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from leonit.code_runner import SourceTooLargeError
from leonit.core.config import Settings
from leonit.core.errors import ValidationFailedError
from leonit.interviews.schemas import CodeRunResultOut, CodeSubmissionOut

if TYPE_CHECKING:
    from leonit.interviews.models import Answer

# Сколько символов вывода программы попадает в текст для оценщика.
_RUN_OUTPUT_LIMIT = 2000


def validate_code(language: str, source: str, settings: Settings) -> str:
    """Проверить язык и размер; вернуть нормализованное имя языка."""
    normalized = language.strip().lower()
    if normalized not in settings.CODE_LANGUAGES:
        raise ValidationFailedError(
            f"Язык «{language}» недоступен; доступны: {', '.join(settings.CODE_LANGUAGES)}"
        )
    size = len(source.encode("utf-8"))
    if size > settings.CODE_MAX_SOURCE_BYTES:
        raise SourceTooLargeError(
            f"Код слишком большой: {size} байт при лимите {settings.CODE_MAX_SOURCE_BYTES}"
        )
    return normalized


def is_submitted(answer: Answer) -> bool:
    return bool((answer.code_submission or {}).get("submitted_at"))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def code_submission_out(data: dict[str, Any] | None) -> CodeSubmissionOut | None:
    if not data:
        return None
    run = data.get("run_result")
    run_out = None
    if isinstance(run, dict) and run.get("status") in ("ok", "error", "timeout"):
        run_out = CodeRunResultOut(
            status=run["status"],
            stdout=str(run.get("stdout") or ""),
            stderr=str(run.get("stderr") or ""),
            exit_code=run.get("exit_code"),
            duration_ms=int(run.get("duration_ms") or 0),
            ran_at=_parse_dt(run.get("ran_at")),
        )
    return CodeSubmissionOut(
        language=str(data.get("language") or ""),
        source=str(data.get("source") or ""),
        submitted_at=_parse_dt(data.get("submitted_at")),
        run_result=run_out,
    )


def _clip(text: str) -> str:
    text = text.strip()
    if len(text) <= _RUN_OUTPUT_LIMIT:
        return text
    return text[:_RUN_OUTPUT_LIMIT] + "…"


def report_transcript(answer: Answer) -> str | None:
    """Текст ответа для отчёта: транскрипт видео, а у ответа без видео — код.

    У ответа на вопрос ``kind=code`` без пояснения транскрипта не бывает, и
    единственный «текст ответа» — отправленный код; отдаём его через
    ``answer_text_for_evaluation``, чтобы потребители API, читающие только
    ``transcript_text`` (экспорт, поиск), тоже видели ответ.
    """
    if answer.transcript_text:
        return answer.transcript_text
    if answer.media_key is None and is_submitted(answer):
        return answer_text_for_evaluation(answer)
    return None


def answer_text_for_evaluation(answer: Answer) -> str | None:
    """Полный текст ответа для оценщика: транскрипт плюс отправленный код.

    Код оборачивается в fenced-блок с языком, чтобы модель отличала его от
    речи; результат запуска (если был) прилагается коротко. Черновик без
    отправки не считается ответом и не попадает в текст.
    """
    parts: list[str] = []
    transcript = (answer.transcript_text or "").strip()
    if transcript:
        parts.append(transcript)
    code = answer.code_submission or {}
    source = str(code.get("source") or "")
    if code.get("submitted_at") and source.strip():
        language = str(code.get("language") or "").strip()
        block = f"```{language}\n{source.rstrip()}\n```"
        run = code.get("run_result")
        if isinstance(run, dict) and run.get("status"):
            lines = [f"Результат запуска: {run['status']}"]
            if run.get("exit_code") is not None:
                lines[0] += f" (код выхода {run['exit_code']})"
            if run.get("stdout"):
                lines.append(f"stdout:\n{_clip(str(run['stdout']))}")
            if run.get("stderr"):
                lines.append(f"stderr:\n{_clip(str(run['stderr']))}")
            block += "\n\n" + "\n".join(lines)
        parts.append(block)
    return "\n\n".join(parts) or None
