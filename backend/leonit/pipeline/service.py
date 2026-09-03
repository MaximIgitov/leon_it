"""Обработка ответа кандидата и чистка медиа по сроку хранения.

Шаги обработки идемпотентны: повтор задачи после сбоя заново читает метаданные,
перезаписывает аудио и ремукс и снова вызывает STT. Промежуточный результат
(метаданные, аудио, ремукс) коммитится до транскрибации — если упал провайдер
STT, у сотрудника уже есть аудио и метаданные, а повтор не начинает с нуля.

Ответ переводится в ``processing`` условным UPDATE (compare-and-set): два
воркера не могут взять один ответ одновременно, даже если очередь отдала
задачу «зомби»-перехватом. Обработка, прерванная остановкой воркера, возвращает
ответ в ``uploaded``; ответ, брошенный убитым воркером, считается протухшим по
``updated_at`` и берётся заново (сразу — если пришла задача, иначе — тиком
воркера, см. ``jobs.py``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.accounts.models import Organization
from leonit.ai.gateway import get_stt
from leonit.ai.providers.base import STTProvider
from leonit.ai.providers.openai_compatible import MAX_AUDIO_BYTES
from leonit.candidates.models import Interview, InterviewStatus
from leonit.core.config import get_settings
from leonit.core.logging import get_logger
from leonit.core.storage import LocalStorage, Storage, get_storage
from leonit.core.time import utcnow
from leonit.interviews.models import Answer, AnswerStatus
from leonit.interviews.service import ANSWER_PROCESS_JOB
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
# Лимит STT-провайдера на размер файла: скопированный Opus длинного ответа
# может его превысить — тогда дорожка перекодируется в компактный моно 16 кГц.
STT_MAX_AUDIO_BYTES = MAX_AUDIO_BYTES
INTERRUPTED_MESSAGE = "обработка прервана остановкой воркера и будет повторена"
_ERROR_MAX_CHARS = 2000
_PROMPT_MAX_TERMS = 40
_PROMPT_MAX_CHARS = 600
_LANGUAGE_MAX_CHARS = 16
# Что в media_meta пересобирается на каждой попытке (остальное — например,
# purged_at — переживает повторную обработку).
_REBUILT_META_KEYS: frozenset[str] = frozenset(
    {"playback_key", "playback_error", "audio_copied", "stt_model"}
)
# Интервью, которые кандидат не довёл до конца: медиа чистится по сроку
# хранения от истечения ссылки, иначе брошенная запись хранилась бы вечно.
_ABANDONED_STATUSES: tuple[InterviewStatus, ...] = (
    InterviewStatus.in_progress,
    InterviewStatus.expired,
)


class AnswerBusyError(PipelineError):
    """Ответ прямо сейчас обрабатывает другой воркер: задачу стоит повторить позже."""


# ------------------------------------------------------------------ helpers


def audio_key_for(media_key: str) -> str:
    """Ключ аудиодорожки рядом с видео: ``…/q00-a1-<id>.webm`` → ``…/q00-a1-<id>.ogg``."""
    path = PurePosixPath(media_key)
    return str(path.with_name(f"{path.stem}.ogg"))


def playback_key_for(media_key: str) -> str:
    path = PurePosixPath(media_key)
    return str(path.with_name(f"{path.stem}.playback.webm"))


def interview_prefix(interview_id: UUID) -> str:
    """Каталог всех файлов интервью в хранилище (см. ``InterviewRoomService``)."""
    return f"interviews/{interview_id}"


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


def stale_processing_threshold() -> timedelta:
    return timedelta(seconds=get_settings().PIPELINE_STALE_PROCESSING_S)


def _local(storage: Storage) -> LocalStorage:
    # ffmpeg работает с путями, а не с потоками: абстракция Storage нужна для
    # чтения/проверки/удаления, но для обработки нужен локальный том.
    if not isinstance(storage, LocalStorage):
        raise PipelineError("медиа-пайплайн работает только с локальным хранилищем")
    return storage


async def _read_all(storage: Storage, key: str) -> bytes:
    return b"".join([chunk async for chunk in storage.open_range(key)])


def _file_size(path: Path) -> int:
    return path.stat().st_size


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


async def claim_answer(session: AsyncSession, answer_id: UUID, *, now: datetime) -> bool:
    """Занять ответ под обработку одним условным UPDATE.

    Берутся ``uploaded``/``failed`` и протухшие ``processing`` (без движения
    дольше ``PIPELINE_STALE_PROCESSING_S``). ``rowcount == 0`` значит, что ответ
    либо уже обработан, либо его держит живой воркер.
    """
    stale_before = now - stale_processing_threshold()
    result = await session.execute(
        update(Answer)
        .where(
            Answer.id == answer_id,
            or_(
                Answer.status.in_(list(PROCESSABLE_STATUSES)),
                and_(
                    Answer.status == AnswerStatus.processing,
                    Answer.updated_at < stale_before,
                ),
            ),
        )
        .values(status=AnswerStatus.processing, processing_error=None, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return bool(result.rowcount)


async def process_answer(
    session: AsyncSession,
    answer_id: UUID,
    *,
    storage: Storage | None = None,
    stt: STTProvider | None = None,
) -> dict[str, Any]:
    """Полный цикл по одному ответу: probe → аудио → ремукс → транскрипт.

    Ответ ``done``/``recording``/``abandoned`` пропускается. ``processing``
    у живого воркера — ``AnswerBusyError``: очередь повторит задачу с паузой, а
    если ответ так и останется брошенным, его вернёт в очередь тик воркера.
    Ошибка любого шага переводит ответ в ``failed`` с текстом ошибки и
    пробрасывается дальше — очередь повторит задачу, и повтор корректно
    стартует из ``failed``. Отмена (остановка воркера) возвращает ``uploaded``.
    """
    storage = storage or get_storage()
    answer = await session.get(Answer, answer_id)
    if answer is None:
        return {"skipped": "answer not found", "answer_id": str(answer_id)}
    if answer.status not in PROCESSABLE_STATUSES and answer.status != AnswerStatus.processing:
        return {"skipped": f"status is {answer.status.value}", "answer_id": str(answer_id)}
    if (answer.media_meta or {}).get("purged_at") or not answer.media_key:
        return {"skipped": "media is purged", "answer_id": str(answer_id)}
    if not await claim_answer(session, answer_id, now=utcnow()):
        await session.refresh(answer)
        if answer.status == AnswerStatus.processing:
            raise AnswerBusyError("ответ уже обрабатывается другим воркером")
        return {"skipped": f"status is {answer.status.value}", "answer_id": str(answer_id)}
    await session.refresh(answer)

    interview = await session.get(Interview, answer.interview_id)
    vacancy = await session.get(Vacancy, interview.vacancy_id) if interview else None
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
    except BaseException:
        # Отмена задачи (graceful stop, потеря аренды) или остановка процесса:
        # это не ошибка ответа, его нужно вернуть под повторную обработку.
        # shield — чтобы повторная отмена не оборвала сам откат статуса.
        await asyncio.shield(_mark_interrupted(session, answer_id))
        raise


async def _mark_interrupted(session: AsyncSession, answer_id: UUID) -> None:
    try:
        await session.rollback()
        await session.execute(
            update(Answer)
            .where(Answer.id == answer_id, Answer.status == AnswerStatus.processing)
            .values(status=AnswerStatus.uploaded, processing_error=INTERRUPTED_MESSAGE)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        log.warning("answer.process interrupted answer=%s, returned to uploaded", answer_id)
    except Exception:  # лог важнее, чем исключение поверх отмены
        log.exception("answer.process interrupted answer=%s, status not restored", answer_id)


async def _touch(session: AsyncSession, answer: Answer) -> None:
    """Отметить движение по ответу: по ``updated_at`` отличают живую обработку от брошенной."""
    answer.updated_at = utcnow()
    await session.commit()


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
    audio_path = local.path_for(audio_key)
    copied = await ffmpeg.extract_audio(source_path, audio_path, source=source)
    if copied and await asyncio.to_thread(_file_size, audio_path) > STT_MAX_AUDIO_BYTES:
        # Длинный ответ с браузерным битрейтом не влезает в лимит провайдера:
        # перекодируем в компактную дорожку, в ней те же слова.
        copied = await ffmpeg.extract_audio(
            source_path, audio_path, source=source, force_transcode=True
        )
    meta["audio_copied"] = copied
    if meta.get("duration_s") is None:
        # WebM из MediaRecorder часто без длительности в заголовке; у извлечённого
        # Ogg она есть всегда.
        meta["duration_s"] = (await ffmpeg.probe(audio_path)).duration_s
    await _touch(session, answer)

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
    meta = {**meta, "stt_model": stt.model}
    # Пока шла обработка, мог сработать срок хранения: транскрипт сохраняем
    # (он и есть цель), а файлы, созданные после чистки, убираем.
    current_meta = await session.scalar(select(Answer.media_meta).where(Answer.id == answer.id))
    purged_at = (current_meta or {}).get("purged_at")
    if purged_at:
        for key in (audio_key, meta.get("playback_key")):
            if key:
                await storage.delete(key)
        meta = {key: value for key, value in meta.items() if key != "playback_key"}
        meta["purged_at"] = purged_at
        answer.media_key = None
        answer.audio_key = None
        log.info("answer.process finished after purge answer=%s: files dropped", answer.id)
    answer.transcript_text = transcript.text
    answer.transcript_segments = _segments(transcript.segments)
    answer.transcript_language = (transcript.language or language)[:_LANGUAGE_MAX_CHARS]
    answer.media_meta = meta
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


async def requeue_stale_answers(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Вернуть в очередь ответы, брошенные в ``processing`` убитым воркером.

    Статус сбрасывается в ``uploaded`` и ставится задача ``answer.process`` с
    обычным ключом дедупликации; если по ответу уже есть активная задача,
    новая не создаётся. Вызывается тиком воркера.
    """
    now = now or utcnow()
    stale_before = now - stale_processing_threshold()
    stale = (
        await session.scalars(
            select(Answer).where(
                Answer.status == AnswerStatus.processing, Answer.updated_at < stale_before
            )
        )
    ).all()
    for answer in stale:
        answer.status = AnswerStatus.uploaded
        answer.processing_error = INTERRUPTED_MESSAGE
        await jobs.enqueue(
            session,
            ANSWER_PROCESS_JOB,
            {"answer_id": str(answer.id), "interview_id": str(answer.interview_id)},
            dedupe_key=f"answer:{answer.id}",
        )
        log.warning("answer.process stale answer=%s requeued", answer.id)
    if stale:
        await session.commit()
    return len(stale)


# -------------------------------------------------------------- retention


def _media_keys(answer: Answer) -> list[str]:
    keys = [answer.media_key, answer.audio_key, (answer.media_meta or {}).get("playback_key")]
    return [key for key in keys if isinstance(key, str) and key]


async def _expired_interviews(
    session: AsyncSession, organization: Organization, cutoff: datetime
) -> list[UUID]:
    finished_at = func.coalesce(Interview.completed_at, Interview.cancelled_at)
    return list(
        (
            await session.scalars(
                select(Interview.id).where(
                    Interview.organization_id == organization.id,
                    or_(
                        and_(finished_at.is_not(None), finished_at < cutoff),
                        and_(
                            Interview.status.in_(list(_ABANDONED_STATUSES)),
                            Interview.expires_at < cutoff,
                        ),
                    ),
                )
            )
        ).all()
    )


async def purge_expired_media(
    session: AsyncSession,
    *,
    storage: Storage | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Удалить медиа ответов интервью, завершённых раньше срока хранения организации.

    Срок считается от завершения (или отмены) интервью; для брошенных
    интервью (``in_progress``/``expired``) — от истечения ссылки. Удаляются
    только файлы (видео, аудио, ремукс): транскрипт, метаданные и оценка
    остаются — по ним отчёт читается и после чистки. Ключи обнуляются, в
    ``media_meta.purged_at`` пишется время, поэтому повторный запуск ничего не
    найдёт — задача идемпотентна. Ответы в ``processing`` пропускаются: их
    файлы прямо сейчас читает пайплайн, они попадут в следующий прогон.
    """
    storage = storage or get_storage()
    now = now or utcnow()
    stats = {"organizations": 0, "interviews": 0, "answers": 0, "files": 0, "skipped": 0}
    organizations = (await session.scalars(select(Organization))).all()
    for organization in organizations:
        cutoff = now - timedelta(days=max(int(organization.retention_days), 0))
        interviews = await _expired_interviews(session, organization, cutoff)
        if not interviews:
            continue
        answers = (
            await session.scalars(select(Answer).where(Answer.interview_id.in_(interviews)))
        ).all()
        touched_interviews: set[UUID] = set()
        busy_interviews: set[UUID] = set()
        for answer in answers:
            keys = _media_keys(answer)
            if not keys:
                continue
            if answer.status == AnswerStatus.processing:
                busy_interviews.add(answer.interview_id)
                stats["skipped"] += 1
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
            # Каталог интервью целиком: там же остаются осиротевшие .part и
            # другие файлы, о которых ответы не знают. Но не пока какой-то
            # ответ интервью ещё обрабатывается.
            delete_prefix = getattr(storage, "delete_prefix", None)
            if delete_prefix is not None:
                for interview_id in touched_interviews - busy_interviews:
                    await delete_prefix(interview_prefix(interview_id))
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


async def ensure_purge_schedule(session: AsyncSession, *, now: datetime | None = None) -> list[Job]:
    """Страховка расписания: чистка на сегодня и на завтра должны существовать.

    Самопланирование «задача ставит следующую» рвётся, если задача дня
    исчерпала попытки; тик воркера восстанавливает цепочку.
    """
    now = now or utcnow()
    today = await schedule_daily_purge(session, day=now.date(), now=now)
    tomorrow = await schedule_daily_purge(session, day=now.date() + timedelta(days=1), now=now)
    return [today, tomorrow]
