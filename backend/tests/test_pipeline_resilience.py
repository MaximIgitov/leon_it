"""Медиа-пайплайн под сбоями: отмена, гонки, протухшие ответы, чистка.

Дополняет ``test_pipeline.py`` сценариями «что, если»: прерванная обработка
возвращается в очередь, два воркера не берут один ответ, брошенные интервью
попадают под срок хранения, цепочка ежедневной чистки не рвётся, а ошибки
ffmpeg не раскрывают пути сервера.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from leonit.accounts.models import Organization
from leonit.ai.providers.base import STTProvider, Transcript, TranscriptSegment
from leonit.candidates.models import Interview, InterviewStatus
from leonit.core.config import get_settings
from leonit.core.db import get_session_maker
from leonit.core.storage import get_storage
from leonit.core.time import utcnow
from leonit.interviews.models import Answer, AnswerStatus
from leonit.jobs.models import Job, JobStatus
from leonit.jobs.registry import load_all_handlers, tick_hooks
from leonit.jobs.worker import Worker
from leonit.pipeline import ffmpeg, service
from leonit.pipeline import jobs as pipeline_jobs
from leonit.pipeline.ffmpeg import PipelineError, sanitize_paths
from leonit.pipeline.service import (
    INTERRUPTED_MESSAGE,
    RETENTION_PURGE_JOB,
    AnswerBusyError,
    claim_answer,
    interview_prefix,
    process_answer,
    purge_expired_media,
    requeue_stale_answers,
    stale_processing_threshold,
)
from tests.test_pipeline import FFMPEG_AVAILABLE, _answer, _context, _started, _upload_file

needs_ffmpeg = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe не найдены в PATH")


class _SlowSTT(STTProvider):
    """STT, который «думает» долго: даёт время отменить или перехватить обработку."""

    model = "slow-stt"

    def __init__(self, delay_s: float = 30.0) -> None:
        self.delay_s = delay_s
        self.started = asyncio.Event()

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str = "ru",
        prompt: str | None = None,
    ) -> Transcript:
        self.started.set()
        await asyncio.sleep(self.delay_s)
        return Transcript(
            text="медленно", segments=[TranscriptSegment(0.0, 1.0, "медленно")], language=language
        )


async def _new_answer(client: AsyncClient) -> tuple[str, str]:
    """Ответ в статусе ``uploaded`` без реального файла: для тестов захвата и очереди."""
    _, interview, link, _ = await _started(client)
    created = await client.post(
        f"/api/public/invitations/{link}/questions/0/answers", json={"mime_type": "video/webm"}
    )
    answer_id = created.json()["answer"]["id"]
    async with get_session_maker()() as session:
        await session.execute(
            update(Answer)
            .where(Answer.id == uuid.UUID(answer_id))
            .values(status=AnswerStatus.uploaded)
        )
        await session.commit()
    return answer_id, interview["id"]


async def _set(answer_id: str, **values: object) -> None:
    async with get_session_maker()() as session:
        await session.execute(
            update(Answer).where(Answer.id == uuid.UUID(answer_id)).values(**values)
        )
        await session.commit()


async def _expire_org_and_interview(
    interview_id: str, *, status: InterviewStatus | None = None
) -> None:
    """Срок хранения 0 дней и просроченная ссылка: интервью попадает под чистку сразу."""
    async with get_session_maker()() as session:
        organization_id = await session.scalar(
            select(Interview.organization_id).where(Interview.id == uuid.UUID(interview_id))
        )
        await session.execute(
            update(Organization).where(Organization.id == organization_id).values(retention_days=0)
        )
        values: dict[str, object] = {"expires_at": utcnow() - timedelta(days=1)}
        if status is not None:
            values["status"] = status
        await session.execute(
            update(Interview).where(Interview.id == uuid.UUID(interview_id)).values(**values)
        )
        await session.commit()


# ------------------------------------------------------------ захват ответа


async def test_claim_is_compare_and_set_and_reclaims_stale(client: AsyncClient) -> None:
    answer_id, _ = await _new_answer(client)
    now = utcnow()
    async with get_session_maker()() as session:
        assert await claim_answer(session, uuid.UUID(answer_id), now=now)
        # Живой processing второму воркеру не достаётся.
        assert not await claim_answer(session, uuid.UUID(answer_id), now=now + timedelta(seconds=1))
        # …а протухший (воркер убит, updated_at не двигается) — достаётся.
        later = now + stale_processing_threshold() + timedelta(seconds=1)
        assert await claim_answer(session, uuid.UUID(answer_id), now=later)
        # done/recording не берутся никогда.
        await session.execute(
            update(Answer).where(Answer.id == uuid.UUID(answer_id)).values(status=AnswerStatus.done)
        )
        await session.commit()
        assert not await claim_answer(session, uuid.UUID(answer_id), now=later)


async def test_busy_answer_raises_retryable_error(client: AsyncClient) -> None:
    answer_id, _ = await _new_answer(client)
    async with get_session_maker()() as session:
        assert await claim_answer(session, uuid.UUID(answer_id), now=utcnow())
        with pytest.raises(AnswerBusyError):
            await process_answer(session, uuid.UUID(answer_id))
    # AnswerBusyError — обычная ошибка обработчика: очередь повторит задачу с паузой.
    assert issubclass(AnswerBusyError, PipelineError)
    assert (await _answer(answer_id)).status == AnswerStatus.processing


@needs_ffmpeg
async def test_interrupted_processing_returns_to_uploaded_and_retry_finishes(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    _, _, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, samples["webm"], "video/webm")
    slow = _SlowSTT()

    async def run() -> dict:
        async with get_session_maker()() as session:
            return await process_answer(session, uuid.UUID(uploaded["id"]), stt=slow)

    task = asyncio.create_task(run())
    await asyncio.wait_for(slow.started.wait(), timeout=60)
    assert (await _answer(uploaded["id"])).status == AnswerStatus.processing
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    interrupted = await _answer(uploaded["id"])
    assert interrupted.status == AnswerStatus.uploaded
    assert interrupted.processing_error == INTERRUPTED_MESSAGE
    # Аудио и метаданные прошлой попытки уже сохранены; повтор доходит до конца.
    assert interrupted.audio_key and interrupted.media_meta.get("video_codec") == "vp8"
    result = await pipeline_jobs.process_answer_job({"answer_id": uploaded["id"]}, _context())
    assert result is not None and "skipped" not in result
    done = await _answer(uploaded["id"])
    assert done.status == AnswerStatus.done and done.processing_error is None


@needs_ffmpeg
async def test_second_worker_cannot_take_answer_in_progress(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    _, _, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, samples["webm"], "video/webm")
    slow = _SlowSTT()

    async def run() -> dict:
        async with get_session_maker()() as session:
            return await process_answer(session, uuid.UUID(uploaded["id"]), stt=slow)

    task = asyncio.create_task(run())
    await asyncio.wait_for(slow.started.wait(), timeout=60)
    async with get_session_maker()() as session:
        with pytest.raises(AnswerBusyError):
            await process_answer(session, uuid.UUID(uploaded["id"]))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await _answer(uploaded["id"])).status == AnswerStatus.uploaded


async def test_stale_processing_answers_are_requeued_by_worker_tick(client: AsyncClient) -> None:
    answer_id, interview_id = await _new_answer(client)
    stale_at = utcnow() - stale_processing_threshold() - timedelta(minutes=1)
    await _set(answer_id, status=AnswerStatus.processing, updated_at=stale_at)
    fresh_id, _ = await _new_answer(client)
    await _set(fresh_id, status=AnswerStatus.processing)

    async with get_session_maker()() as session:
        assert await requeue_stale_answers(session) == 1
        job_ = await session.scalar(select(Job).where(Job.dedupe_key == f"answer:{answer_id}"))
        assert job_ is not None and job_.status == JobStatus.queued
        assert job_.payload == {"answer_id": answer_id, "interview_id": interview_id}
        # Повтор ничего не находит: ответ уже uploaded.
        assert await requeue_stale_answers(session) == 0
    requeued = await _answer(answer_id)
    assert requeued.status == AnswerStatus.uploaded
    assert requeued.processing_error == INTERRUPTED_MESSAGE
    assert (await _answer(fresh_id)).status == AnswerStatus.processing

    # Хук тика зарегистрирован и не падает; он же страхует расписание чистки.
    load_all_handlers()
    assert pipeline_jobs.pipeline_maintenance in tick_hooks()
    worker = Worker(worker_id="w-tick", kinds=[RETENTION_PURGE_JOB], tick_interval_s=0)
    await worker.run_tick_hooks()
    async with get_session_maker()() as session:
        for day in (utcnow().date(), utcnow().date() + timedelta(days=1)):
            job_ = await session.scalar(
                select(Job).where(Job.dedupe_key == f"retention:purge:{day.isoformat()}")
            )
            assert job_ is not None, day


# ------------------------------------------------------------------ чистка


async def test_purge_job_schedules_tomorrow_before_purging(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(session, **kwargs):
        raise RuntimeError("диск недоступен")

    monkeypatch.setattr(pipeline_jobs, "purge_expired_media", boom)
    with pytest.raises(RuntimeError):
        await pipeline_jobs.purge_expired_media_job({"date": "x"}, _context())
    tomorrow = utcnow().date() + timedelta(days=1)
    async with get_session_maker()() as session:
        next_job = await session.scalar(
            select(Job).where(Job.dedupe_key == f"retention:purge:{tomorrow.isoformat()}")
        )
    assert next_job is not None


@needs_ffmpeg
async def test_purge_covers_abandoned_in_progress_interview_and_zero_retention(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    _, interview, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, samples["webm"], "video/webm")
    async with get_session_maker()() as session:
        await process_answer(session, uuid.UUID(uploaded["id"]))
    before = await _answer(uploaded["id"])
    storage = get_storage()
    assert await storage.exists(before.media_key)

    # Пока ссылка действует, брошенное интервью не трогаем даже при сроке 0.
    async with get_session_maker()() as session:
        organization_id = await session.scalar(
            select(Interview.organization_id).where(Interview.id == uuid.UUID(interview["id"]))
        )
        await session.execute(
            update(Organization).where(Organization.id == organization_id).values(retention_days=0)
        )
        await session.commit()
        assert (await purge_expired_media(session))["answers"] == 0
    assert (await _answer(uploaded["id"])).media_key

    await _expire_org_and_interview(interview["id"])
    assert (await _answer(uploaded["id"])).status == AnswerStatus.done
    async with get_session_maker()() as session:
        stats = await purge_expired_media(session)
    assert stats["answers"] == 1 and stats["files"] == 3 and stats["skipped"] == 0
    purged = await _answer(uploaded["id"])
    assert purged.media_key is None and purged.media_meta["purged_at"]
    assert purged.transcript_text == before.transcript_text
    # Каталог интервью удалён целиком — вместе с возможными осиротевшими .part.
    assert not storage.path_for(interview_prefix(uuid.UUID(interview["id"]))).exists()  # type: ignore[attr-defined]


@needs_ffmpeg
async def test_purge_skips_answers_being_processed(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    _, interview, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, samples["webm"], "video/webm")
    async with get_session_maker()() as session:
        await process_answer(session, uuid.UUID(uploaded["id"]))
    await _expire_org_and_interview(interview["id"], status=InterviewStatus.expired)
    await _set(uploaded["id"], status=AnswerStatus.processing)

    storage = get_storage()
    async with get_session_maker()() as session:
        stats = await purge_expired_media(session)
    assert stats["skipped"] == 1 and stats["answers"] == 0
    busy = await _answer(uploaded["id"])
    assert busy.media_key and await storage.exists(busy.media_key)
    assert storage.path_for(interview_prefix(uuid.UUID(interview["id"]))).exists()  # type: ignore[attr-defined]

    await _set(uploaded["id"], status=AnswerStatus.done)
    async with get_session_maker()() as session:
        stats = await purge_expired_media(session)
    assert stats["answers"] == 1
    assert not await storage.exists(busy.media_key)


@needs_ffmpeg
async def test_processing_that_outlives_purge_keeps_transcript_but_not_files(
    client: AsyncClient, samples: dict[str, Path]
) -> None:
    _, _, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, samples["webm"], "video/webm")
    storage = get_storage()

    class _PurgingSTT(STTProvider):
        """Пока шло распознавание, чистка успела удалить оригинал и пометить ответ."""

        model = "purge-stt"

        async def transcribe(self, audio, *, content_type, language="ru", prompt=None):
            answer = await _answer(uploaded["id"])
            await storage.delete(answer.media_key)
            await _set(
                uploaded["id"],
                media_key=None,
                audio_key=None,
                media_meta={**answer.media_meta, "purged_at": utcnow().isoformat()},
            )
            return Transcript(text="успели", segments=[], language=language)

    async with get_session_maker()() as session:
        result = await process_answer(session, uuid.UUID(uploaded["id"]), stt=_PurgingSTT())
    assert result["transcript_chars"] == len("успели")
    done = await _answer(uploaded["id"])
    assert done.status == AnswerStatus.done and done.transcript_text == "успели"
    assert done.media_key is None and done.audio_key is None
    assert done.media_meta["purged_at"] and "playback_key" not in done.media_meta
    assert not await storage.exists(service.audio_key_for(uploaded["id"]))
    assert not list(storage.path_for(interview_prefix(done.interview_id)).glob("*"))  # type: ignore[attr-defined]


# ------------------------------------------------------------------ ffmpeg


@needs_ffmpeg
async def test_timeout_keeps_previous_output_and_leaves_no_part(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dst = tmp_path / "audio.ogg"
    dst.write_bytes(b"old")
    (tmp_path / "audio.ogg.deadbeefcafe.part").write_bytes(b"stale")
    monkeypatch.setattr(ffmpeg, "_timeout_s", lambda: 0.01)
    with pytest.raises(PipelineError, match="таймаут"):
        await ffmpeg._run_to_file(
            ["-f", "lavfi", "-i", "sine=duration=60", "-c:a", "libopus"], dst, container="ogg"
        )
    assert dst.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.part"))


@needs_ffmpeg
async def test_oversized_copied_opus_is_transcoded(
    client: AsyncClient, samples: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "STT_MAX_AUDIO_BYTES", 1)
    _, _, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, samples["webm"], "video/webm")
    async with get_session_maker()() as session:
        result = await process_answer(session, uuid.UUID(uploaded["id"]))
    assert result["audio_copied"] is False
    answer = await _answer(uploaded["id"])
    assert answer.media_meta["audio_copied"] is False
    extracted = await ffmpeg.probe(get_storage().path_for(answer.audio_key))  # type: ignore[attr-defined]
    assert extracted.audio_codec == "opus" and extracted.audio_channels == 1


def test_sanitize_paths_hides_media_root() -> None:
    root = get_settings().MEDIA_ROOT
    text = f"{root.resolve()}/interviews/x/q00.webm: Invalid data; also {root}"
    cleaned = sanitize_paths(text)
    assert str(root.resolve()) not in cleaned and cleaned.startswith(
        "<media>/interviews/x/q00.webm"
    )
    assert sanitize_paths("nothing to hide") == "nothing to hide"


@needs_ffmpeg
async def test_processing_error_does_not_leak_server_paths(
    client: AsyncClient, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.webm"
    broken.write_bytes(b"\x1aE\xdf\xa3" + b"\x00garbage" * 300)
    _, _, link, _ = await _started(client)
    uploaded = await _upload_file(client, link, 0, broken, "video/webm")
    with pytest.raises(PipelineError):
        await pipeline_jobs.process_answer_job({"answer_id": uploaded["id"]}, _context())
    failed = await _answer(uploaded["id"])
    assert failed.processing_error
    root = get_settings().MEDIA_ROOT
    assert str(root.resolve()) not in failed.processing_error
    assert str(root) not in failed.processing_error
