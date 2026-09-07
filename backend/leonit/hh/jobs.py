"""Задача ``hh.sync``: периодическая и внеочередная синхронизация с HH.

Периодическая задача ставит следующую сама (ключ — минута запуска), воркер на
старте и раз в час тиком проверяет, что активная задача есть, — цепочка не
рвётся ни после рестарта, ни после исчерпанных попыток. Вебхук и кнопка
«синхронизировать сейчас» ставят задачу организации с dedupe-ключом.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leonit.core.config import get_settings
from leonit.core.logging import get_logger
from leonit.core.time import utcnow
from leonit.hh.service import (
    HH_SYNC_JOB,
    ensure_periodic_sync,
    schedule_periodic_sync,
    sync_organizations,
)
from leonit.jobs.registry import JobContext, job, on_worker_start, on_worker_tick

log = get_logger(__name__)

# Периодическая и внеочередная синхронизации могут попасть в воркер одновременно
# (у них разные dedupe-ключи). Две параллельные синхронизации читали один и тот же
# ответ кандидата и обе выпускали ссылку: в чат уходила одна, а в базе оставался
# хеш другой — «ссылка недействительна». Замок сериализует запуски в процессе воркера.
_SYNC_LOCK = asyncio.Lock()


@job(HH_SYNC_JOB, resource="llm")
async def hh_sync_job(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any] | None:
    async with ctx.session_maker() as session:
        result: dict[str, Any] = {}
        if payload.get("periodic"):
            interval = timedelta(minutes=get_settings().HH_SYNC_INTERVAL_MINUTES)
            next_job = await schedule_periodic_sync(session, run_after=utcnow() + interval)
            await session.commit()
            result["next_job_id"] = str(next_job.id)
        organization_id = payload.get("organization_id")
        if _SYNC_LOCK.locked():
            log.info("hh.sync waits for a running sync payload=%s", payload)
        async with _SYNC_LOCK:
            stats = await sync_organizations(
                session, organization_id=UUID(str(organization_id)) if organization_id else None
            )
        log.info("hh.sync payload=%s stats=%s", payload, stats)
        return {**result, **stats}


@on_worker_start
async def schedule_hh_sync_on_start(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        job_ = await ensure_periodic_sync(session)
        await session.commit()
        log.info("hh.sync scheduled job=%s run_after=%s", job_.id, job_.run_after)


@on_worker_tick
async def hh_sync_maintenance(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        job_ = await ensure_periodic_sync(session)
        await session.commit()
        log.info("hh.sync maintenance active_job=%s", job_.id)
