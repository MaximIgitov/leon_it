"""Жизненный цикл задачи: постановка, захват, завершение, повтор.

Функции работают в сессии вызывающего и делают ``flush``, но не ``commit``:
постановка задачи должна попадать в одну транзакцию с доменным изменением.
Исключение по смыслу — ``claim_next``: воркер коммитит сразу после захвата,
иначе ``FOR UPDATE`` держит строку и другие воркеры её пропускают.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Update, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.core.errors import ConflictError, NotFoundError
from leonit.core.time import utcnow
from leonit.jobs.models import Job, JobStatus

DEFAULT_LEASE_S = 60
BACKOFF_BASE_S = 5
BACKOFF_CAP_S = 600
_MAX_ERROR_CHARS = 8000


def backoff_delay_s(attempts: int) -> int:
    """Пауза перед повтором: 5с × 2^attempts, не больше 10 минут."""
    return min(BACKOFF_BASE_S * 2 ** max(attempts, 0), BACKOFF_CAP_S)


def _expired_lease(now: datetime):
    """Условие «зомби»: задача running, но воркер перестал продлевать аренду."""
    return and_(Job.status == JobStatus.running, Job.lease_until < now)


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 5,
) -> Job:
    """Поставить задачу; при активной задаче с тем же ``dedupe_key`` вернуть её."""
    if dedupe_key:
        existing = await session.scalar(select(Job).where(Job.dedupe_key == dedupe_key))
        if existing is not None:
            if not existing.is_terminal:
                return existing
            # Завершённая задача не должна мешать новой обработке той же сущности:
            # освобождаем ключ, история остаётся в строке.
            existing.dedupe_key = None
            await session.flush()
    job = Job(
        kind=kind,
        payload=payload or {},
        status=JobStatus.queued,
        run_after=run_after or utcnow(),
        dedupe_key=dedupe_key,
        max_attempts=max_attempts,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError as error:
        # Две постановки с одним ключом в одну миллисекунду: пусть проигравшая
        # сторона повторит запрос, чем ставить дубль.
        raise ConflictError(f"job with dedupe_key {dedupe_key!r} was just enqueued") from error
    return job


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"job {job_id} not found")
    return job


async def list_jobs(
    session: AsyncSession,
    *,
    kind: str | None = None,
    status: JobStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Job]:
    query = select(Job).order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset)
    if kind:
        query = query.where(Job.kind == kind)
    if status:
        query = query.where(Job.status == status)
    return list((await session.scalars(query)).all())


async def claim_next(
    session: AsyncSession,
    worker_id: str,
    kinds: Sequence[str] | None = None,
    *,
    lease_s: int = DEFAULT_LEASE_S,
    now: datetime | None = None,
) -> Job | None:
    """Захватить следующую готовую задачу (или зомби с истёкшей арендой)."""
    now = now or utcnow()

    # Зомби, у которых попытки уже кончились, переводим в failed отдельно:
    # захватывать их бессмысленно, а висеть в running они не должны.
    await session.execute(
        update(Job)
        .where(_expired_lease(now), Job.attempts >= Job.max_attempts)
        .values(
            status=JobStatus.failed,
            lease_until=None,
            locked_by=None,
            finished_at=now,
            updated_at=now,
            last_error=func.coalesce(Job.last_error, "lease expired after the last attempt"),
        )
        .execution_options(synchronize_session=False)
    )

    if kinds is not None and not kinds:
        return None
    skip_locked = session.bind is not None and session.bind.dialect.name == "postgresql"
    statement = claim_statement(worker_id, kinds, now=now, lease_s=lease_s, skip_locked=skip_locked)
    job = (await session.scalars(statement)).one_or_none()
    if job is not None:
        # RETURNING отдаёт строку до синхронизации identity map: обновляем объект.
        await session.refresh(job)
    return job


def claim_statement(
    worker_id: str,
    kinds: Sequence[str] | None,
    *,
    now: datetime,
    lease_s: int,
    skip_locked: bool,
) -> Update:
    """Собрать ``UPDATE … RETURNING`` захвата задачи (отдельно — ради проверки SQL).

    ``skip_locked`` включает ``FOR UPDATE SKIP LOCKED`` в подзапросе кандидата:
    параллельные воркеры не ждут друг друга и не берут одну задачу. SQLite этого
    не умеет, там воркер один.
    """
    ready = or_(and_(Job.status == JobStatus.queued, Job.run_after <= now), _expired_lease(now))
    candidate = select(Job.id).where(ready)
    if kinds is not None:
        candidate = candidate.where(Job.kind.in_(list(kinds)))
    candidate = candidate.order_by(Job.run_after, Job.created_at).limit(1)
    if skip_locked:
        candidate = candidate.with_for_update(skip_locked=True)
    return (
        update(Job)
        .where(Job.id == candidate.scalar_subquery())
        .values(
            status=JobStatus.running,
            locked_by=worker_id,
            lease_until=now + timedelta(seconds=lease_s),
            attempts=Job.attempts + 1,
            started_at=func.coalesce(Job.started_at, now),
            updated_at=now,
        )
        .returning(Job)
        .execution_options(synchronize_session=False)
    )


async def heartbeat(
    session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    *,
    lease_s: int = DEFAULT_LEASE_S,
) -> bool:
    """Продлить аренду; False — задача уже не наша (аренда истекла, её забрали)."""
    now = utcnow()
    result = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.running, Job.locked_by == worker_id)
        .values(lease_until=now + timedelta(seconds=lease_s), updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return (result.rowcount or 0) > 0


def _ensure_owner(job: Job, worker_id: str | None) -> None:
    if worker_id is not None and job.locked_by != worker_id:
        raise ConflictError(
            f"job {job.id} is owned by {job.locked_by!r}, not {worker_id!r}; lease was lost"
        )


async def complete(
    session: AsyncSession,
    job_id: uuid.UUID,
    result: dict[str, Any] | None = None,
    *,
    worker_id: str | None = None,
) -> Job:
    job = await get_job(session, job_id)
    if job.status != JobStatus.running:
        raise ConflictError(f"job {job.id} is {job.status}, not running")
    _ensure_owner(job, worker_id)
    job.status = JobStatus.succeeded
    job.result = result
    job.lease_until = None
    job.locked_by = None
    job.finished_at = utcnow()
    await session.flush()
    return job


async def fail(
    session: AsyncSession,
    job_id: uuid.UUID,
    error: str,
    *,
    retry: bool = True,
    worker_id: str | None = None,
) -> Job:
    """Зафиксировать ошибку: повтор с экспоненциальной паузой или окончательный failed."""
    job = await get_job(session, job_id)
    if job.status != JobStatus.running:
        raise ConflictError(f"job {job.id} is {job.status}, not running")
    _ensure_owner(job, worker_id)
    now = utcnow()
    job.last_error = error[:_MAX_ERROR_CHARS]
    job.lease_until = None
    job.locked_by = None
    if retry and job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        job.run_after = now + timedelta(seconds=backoff_delay_s(job.attempts))
    else:
        job.status = JobStatus.failed
        job.finished_at = now
    await session.flush()
    return job


async def release(session: AsyncSession, job_id: uuid.UUID, worker_id: str) -> Job | None:
    """Вернуть задачу в очередь при остановке воркера, не тратя попытку."""
    job = await session.get(Job, job_id)
    if job is None or job.status != JobStatus.running or job.locked_by != worker_id:
        return None
    job.status = JobStatus.queued
    job.attempts = max(job.attempts - 1, 0)
    job.lease_until = None
    job.locked_by = None
    job.run_after = utcnow()
    await session.flush()
    return job


async def cancel(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await get_job(session, job_id)
    if job.status != JobStatus.queued:
        raise ConflictError(f"only queued jobs can be cancelled; job is {job.status}")
    job.status = JobStatus.cancelled
    job.finished_at = utcnow()
    await session.flush()
    return job


async def retry(session: AsyncSession, job_id: uuid.UUID) -> Job:
    """Кнопка «Переобработать»: вернуть failed/cancelled задачу в очередь с чистым счётчиком."""
    job = await get_job(session, job_id)
    if job.status not in (JobStatus.failed, JobStatus.cancelled):
        raise ConflictError(f"only failed or cancelled jobs can be retried; job is {job.status}")
    job.status = JobStatus.queued
    job.attempts = 0
    job.run_after = utcnow()
    job.lease_until = None
    job.locked_by = None
    job.finished_at = None
    await session.flush()
    return job
