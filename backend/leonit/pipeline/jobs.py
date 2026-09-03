"""Обработчики задач медиа-пайплайна.

``answer.process`` занимает ресурс ``ffmpeg`` (один процесс на воркер), чистка
по сроку хранения — ``default``. Чистка ставится сама себе на завтра и
дополнительно при старте воркера: после рестарта день не пропускается, а
работающий неделями воркер не зависит от рестартов.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leonit.core.logging import get_logger
from leonit.core.time import utcnow
from leonit.interviews.service import ANSWER_PROCESS_JOB
from leonit.jobs.registry import JobContext, job, on_worker_start
from leonit.pipeline.service import (
    RETENTION_PURGE_JOB,
    process_answer,
    purge_expired_media,
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
        stats = await purge_expired_media(session)
        # Следующая чистка — завтра; ключ на дату не даст поставить дубль.
        next_job = await schedule_daily_purge(session, day=utcnow().date() + timedelta(days=1))
        await session.commit()
        log.info("retention.purge stats=%s next_job=%s", stats, next_job.id)
        return {**stats, "next_job_id": str(next_job.id)}


@on_worker_start
async def schedule_purge_on_start(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        job_ = await schedule_daily_purge(session)
        await session.commit()
        log.info("retention.purge scheduled job=%s run_after=%s", job_.id, job_.run_after)
