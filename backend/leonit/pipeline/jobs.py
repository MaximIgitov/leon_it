"""Обработчики задач медиа-пайплайна.

``answer.process`` занимает ресурс ``ffmpeg`` (один процесс на воркер), чистка
по сроку хранения — ``default``. Чистка ставится сама себе на завтра ещё до
начала работы (сбой сегодняшней не рвёт цепочку), при старте воркера и раз в
час тиком воркера: после рестарта день не пропускается, а работающий неделями
воркер не зависит ни от рестартов, ни от успеха предыдущей задачи. Тем же
тиком в очередь возвращаются ответы, брошенные в ``processing`` убитым воркером.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leonit.core.logging import get_logger
from leonit.core.time import utcnow
from leonit.interviews.service import ANSWER_PROCESS_JOB
from leonit.jobs.registry import JobContext, job, on_worker_start, on_worker_tick
from leonit.pipeline.service import (
    RETENTION_PURGE_JOB,
    ensure_purge_schedule,
    process_answer,
    purge_expired_media,
    requeue_stale_answers,
    schedule_daily_purge,
)

log = get_logger(__name__)


@job(ANSWER_PROCESS_JOB, resource="ffmpeg")
async def process_answer_job(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any] | None:
    async with ctx.session_maker() as session:
        return await process_answer(session, UUID(str(payload["answer_id"])))


@job(RETENTION_PURGE_JOB, resource="default")
async def purge_expired_media_job(
    payload: dict[str, Any], ctx: JobContext
) -> dict[str, Any] | None:
    async with ctx.session_maker() as session:
        # Сначала завтрашняя задача, потом чистка: если чистка упадёт и исчерпает
        # попытки, следующая всё равно состоится. Ключ на дату не даст дубль.
        next_job = await schedule_daily_purge(session, day=utcnow().date() + timedelta(days=1))
        await session.commit()
        stats = await purge_expired_media(session)
        log.info("retention.purge stats=%s next_job=%s", stats, next_job.id)
        return {**stats, "next_job_id": str(next_job.id)}


@on_worker_start
async def schedule_purge_on_start(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        job_ = await schedule_daily_purge(session)
        await session.commit()
        log.info("retention.purge scheduled job=%s run_after=%s", job_.id, job_.run_after)


@on_worker_tick
async def pipeline_maintenance(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Раз в час: страховка расписания чистки и возврат брошенных ответов в очередь."""
    async with session_maker() as session:
        scheduled = await ensure_purge_schedule(session)
        requeued = await requeue_stale_answers(session)
        await session.commit()
        log.info(
            "pipeline.maintenance purge_jobs=%s requeued_answers=%s",
            [str(j.id) for j in scheduled],
            requeued,
        )
