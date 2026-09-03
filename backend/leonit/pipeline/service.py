"""Обработка ответа кандидата и чистка медиа по сроку хранения.

Шаги обработки идемпотентны: повтор задачи после сбоя заново читает метаданные,
перезаписывает аудио и ремукс и снова вызывает STT. Промежуточный результат
(метаданные, аудио, ремукс) коммитится до транскрибации — если упал провайдер
STT, у сотрудника уже есть аудио и метаданные, а повтор не начинает с нуля.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.accounts.models import Organization
from leonit.ai.gateway import get_stt
from leonit.ai.providers.base import STTProvider
from leonit.candidates.models import Interview
from leonit.core.config import get_settings
from leonit.core.logging import get_logger
from leonit.core.storage import LocalStorage, Storage, get_storage
from leonit.core.time import utcnow
from leonit.interviews.models import Answer, AnswerStatus
from leonit.jobs import service as jobs
from leonit.jobs.models import Job
from leonit.pipeline import ffmpeg
from leonit.pipeline.ffmpeg import MediaProbe, PipelineError
from leonit.vacancies.models import Vacancy

log = get_logger(__name__)

RETENTION_PURGE_JOB = "retention.purge"
PROCESSABLE_STATUSES: frozenset[AnswerStatus] = frozenset(
    {AnswerStatus.uploaded, AnswerStatus.failed}
)
_ERROR_MAX_CHARS = 2000
_PROMPT_MAX_TERMS = 40
_PROMPT_MAX_CHARS = 600
_LANGUAGE_MAX_CHARS = 16
# Что в media_meta пересобирается на каждой попытке (остальное — например,
# purged_at — переживает повторную обработку).
_REBUILT_META_KEYS: frozenset[str] = frozenset(
    {"playback_key", "playback_error", "audio_copied", "stt_model"}
)


# ------------------------------------------------------------------ helpers


def audio_key_for(media_key: str) -> str:
    """Ключ аудиодорожки рядом с видео: ``…/q00-a1-<id>.webm`` → ``…/q00-a1-<id>.ogg``."""
    path = PurePosixPath(media_key)
    return str(path.with_name(f"{path.stem}.ogg"))


def playback_key_for(media_key: str) -> str:
    path = PurePosixPath(media_key)
    return str(path.with_name(f"{path.stem}.playback.webm"))


def stt_prompt(title: str, skills: Sequence[str]) -> str:
    """Подсказка STT из названия вакансии и навыков.

    Whisper-подобные модели трактуют prompt как «предыдущий контекст» и точнее
    распознают термины, которые в нём встретились (FastAPI, Kubernetes, а не
    «фаст апи»). Лимит у провайдеров небольшой (порядка 200 токенов), поэтому
    список обрезаем, а дубли убираем.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for skill in skills or ():
        term = str(skill).strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    parts: list[str] = []
    if title and title.strip():
        parts.append(f"Собеседование на вакансию «{title.strip()}».")
    if terms:
        parts.append("Термины: " + ", ".join(terms[:_PROMPT_MAX_TERMS]) + ".")
    return " ".join(parts)[:_PROMPT_MAX_CHARS]


def _local(storage: Storage) -> LocalStorage:
    # ffmpeg работает с путями, а не с потоками: абстракция Storage нужна для
    # чтения/проверки/удаления, но для обработки нужен локальный том.
    if not isinstance(storage, LocalStorage):
        raise PipelineError("медиа-пайплайн работает только с локальным хранилищем")
    return storage


async def _read_all(storage: Storage, key: str) -> bytes:
    return b"".join([chunk async for chunk in storage.open_range(key)])


def _segments(transcript_segments: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "start_s": round(float(segment.start_s), 3),
            "end_s": round(float(segment.end_s), 3),
            "text": segment.text,
        }
        for segment in transcript_segments
        if segment.text
    ]


# ------------------------------------------------------------- processing


async def process_answer(
    session: AsyncSession,
    answer_id: UUID,
    *,
    storage: Storage | None = None,
    stt: STTProvider | None = None,
) -> dict[str, Any]:
    """Полный цикл по одному ответу: probe → аудио → ремукс → транскрипт.

    Ответ не в ``uploaded``/``failed`` пропускается: ``processing`` значит, что
    его уже держит другой воркер, ``done`` — что работа сделана. Ошибка любого
    шага переводит ответ в ``failed`` с текстом ошибки и пробрасывается дальше —
    очередь повторит задачу с паузой, и повтор корректно стартует из ``failed``.
    """
    storage = storage or get_storage()
    answer = await session.get(Answer, answer_id)
    if answer is None:
        return {"skipped": "answer not found", "answer_id": str(answer_id)}
    if answer.status not in PROCESSABLE_STATUSES:
        return {"skipped": f"status is {answer.status.value}", "answer_id": str(answer_id)}
    if (answer.media_meta or {}).get("purged_at") or not answer.media_key:
        return {"skipped": "media is purged", "answer_id": str(answer_id)}

    interview = await session.get(Interview, answer.interview_id)
    vacancy = await session.get(Vacancy, interview.vacancy_id) if interview else None
    answer.status = AnswerStatus.processing
    answer.processing_error = None
    await session.commit()
    try:
        return await _run_pipeline(session, answer, vacancy, storage, stt or get_stt())
    except Exception as error:
        # Откат снимает незакоммиченные изменения шага, на котором упали, и
        # возвращает сессию в рабочее состояние, если ошибка пришла из базы.
        await session.rollback()
        failed = await session.get(Answer, answer_id)
        if failed is not None:
            failed.status = AnswerStatus.failed
            failed.processing_error = f"{type(error).__name__}: {error}"[:_ERROR_MAX_CHARS]
            await session.commit()
        log.warning("answer.process failed answer=%s error=%s", answer_id, error)
        raise


async def _run_pipeline(
    session: AsyncSession,
    answer: Answer,
    vacancy: Vacancy | None,
    storage: Storage,
    stt: STTProvider,
) -> dict[str, Any]:
    media_key = answer.media_key
    assert media_key
    if not await storage.exists(media_key):
        raise PipelineError(f"файл записи {media_key!r} не найден в хранилище")
    local = _local(storage)
    source_path = local.path_for(media_key)

    source: MediaProbe = await ffmpeg.probe(source_path)
    if not source.has_audio:
        raise PipelineError("в записи нет аудиодорожки — транскрибировать нечего")
    # Метаданные собираем заново: старые playback/ошибки от прошлой попытки не нужны.
    meta: dict[str, Any] = {
        key: value
        for key, value in (answer.media_meta or {}).items()
        if key not in _REBUILT_META_KEYS
    }
    meta.update(source.as_dict())

    audio_key = audio_key_for(media_key)
    copied = await ffmpeg.extract_audio(source_path, local.path_for(audio_key), source=source)
    meta["audio_copied"] = copied
    if meta.get("duration_s") is None:
        # WebM из MediaRecorder часто без длительности в заголовке; у извлечённого
        # Ogg она есть всегда.
        meta["duration_s"] = (await ffmpeg.probe(local.path_for(audio_key))).duration_s

    if source.is_webm:
        playback_key = playback_key_for(media_key)
        try:
            await ffmpeg.remux(source_path, local.path_for(playback_key))
            meta["playback_key"] = playback_key
        except PipelineError as error:
            # Ремукс — удобство перемотки, а не условие оценки: оригинал
            # воспроизводится и без него, поэтому транскрибацию не останавливаем.
            log.warning("answer.remux failed answer=%s error=%s", answer.id, error)
            meta["playback_error"] = str(error)[:500]

    answer.audio_key = audio_key
    answer.media_meta = meta
    await session.commit()

    audio = await _read_all(storage, audio_key)
    title = vacancy.title if vacancy is not None else ""
    skills = list(vacancy.skills or []) if vacancy is not None else []
    language = (vacancy.language if vacancy is not None else None) or "ru"
    transcript = await stt.transcribe(
        audio,
        content_type="audio/ogg",
        language=language,
        prompt=stt_prompt(title, skills) or None,
    )
    answer.transcript_text = transcript.text
    answer.transcript_segments = _segments(transcript.segments)
    answer.transcript_language = (transcript.language or language)[:_LANGUAGE_MAX_CHARS]
    answer.media_meta = {**meta, "stt_model": stt.model}
    answer.status = AnswerStatus.done
    answer.processing_error = None
    answer.processed_at = utcnow()
    await session.commit()
    log.info(
        "answer.process done answer=%s duration_s=%s audio_copied=%s playback=%s chars=%s",
        answer.id,
        meta.get("duration_s"),
        copied,
        "playback_key" in meta,
        len(transcript.text),
    )
    return {
        "answer_id": str(answer.id),
        "duration_s": meta.get("duration_s"),
        "audio_copied": copied,
        "playback_key": meta.get("playback_key"),
        "transcript_chars": len(transcript.text),
        "segments": len(answer.transcript_segments or []),
    }


# -------------------------------------------------------------- retention


def _media_keys(answer: Answer) -> list[str]:
    keys = [answer.media_key, answer.audio_key, (answer.media_meta or {}).get("playback_key")]
    return [key for key in keys if isinstance(key, str) and key]


async def purge_expired_media(
    session: AsyncSession,
    *,
    storage: Storage | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Удалить медиа ответов интервью, завершённых раньше срока хранения организации.

    Удаляются только файлы (видео, аудио, ремукс): транскрипт, метаданные и
    оценка остаются — по ним отчёт читается и после чистки. Ключи обнуляются,
    в ``media_meta.purged_at`` пишется время, поэтому повторный запуск ничего
    не найдёт — задача идемпотентна.
    """
    storage = storage or get_storage()
    now = now or utcnow()
    stats = {"organizations": 0, "interviews": 0, "answers": 0, "files": 0}
    organizations = (await session.scalars(select(Organization))).all()
    for organization in organizations:
        cutoff = now - timedelta(days=max(int(organization.retention_days), 0))
        finished_at = func.coalesce(Interview.completed_at, Interview.cancelled_at)
        interviews = (
            await session.scalars(
                select(Interview.id).where(
                    Interview.organization_id == organization.id,
                    finished_at.is_not(None),
                    finished_at < cutoff,
                )
            )
        ).all()
        if not interviews:
            continue
        answers = (
            await session.scalars(select(Answer).where(Answer.interview_id.in_(list(interviews))))
        ).all()
        touched_interviews: set[UUID] = set()
        for answer in answers:
            keys = _media_keys(answer)
            if not keys:
                continue
            removed = 0
            for key in keys:
                if await storage.exists(key):
                    if not dry_run:
                        await storage.delete(key)
                    removed += 1
            if not dry_run:
                meta = {
                    key: value
                    for key, value in (answer.media_meta or {}).items()
                    if key != "playback_key"
                }
                meta["purged_at"] = now.isoformat()
                answer.media_key = None
                answer.audio_key = None
                answer.media_meta = meta
            touched_interviews.add(answer.interview_id)
            stats["answers"] += 1
            stats["files"] += removed
            log.info(
                "retention.purge organization=%s interview=%s answer=%s files=%s dry_run=%s",
                organization.id,
                answer.interview_id,
                answer.id,
                removed,
                dry_run,
            )
        if touched_interviews:
            stats["organizations"] += 1
            stats["interviews"] += len(touched_interviews)
        if not dry_run:
            # Коммит на организацию: сбой посреди прогона не откатывает уже
            # удалённые файлы, а повтор просто продолжит с того же места.
            await session.commit()
    return stats


async def schedule_daily_purge(
    session: AsyncSession, *, day: date | None = None, now: datetime | None = None
) -> Job:
    """Поставить чистку на ``day`` (по умолчанию сегодня) не раньше настроенного часа.

    Ключ ``retention:purge:<дата>`` — одна задача в сутки: если она уже есть
    (в любом статусе), новая не ставится. Если настроенный час уже прошёл,
    задача запускается сразу — так воркер после рестарта не пропускает день.
    """
    now = now or utcnow()
    day = day or now.date()
    dedupe_key = f"retention:purge:{day.isoformat()}"
    existing = await session.scalar(select(Job).where(Job.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    scheduled = datetime.combine(day, time(hour=get_settings().RETENTION_PURGE_HOUR_UTC), UTC)
    return await jobs.enqueue(
        session,
        RETENTION_PURGE_JOB,
        {"date": day.isoformat()},
        run_after=max(scheduled, now),
        dedupe_key=dedupe_key,
        max_attempts=3,
    )
