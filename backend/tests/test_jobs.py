from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.core.db import get_session_maker
from leonit.core.errors import ConflictError, NotFoundError
from leonit.core.time import aware, utcnow
from leonit.jobs import service
from leonit.jobs.models import Job, JobStatus
from leonit.jobs.registry import (
    JobContext,
    job,
    load_all_handlers,
    registered_kinds,
    unregister,
)
from leonit.jobs.schemas import JobRead
from leonit.jobs.service import backoff_delay_s
from leonit.jobs.worker import Worker


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_session_maker()() as session:
        yield session


@pytest.fixture
def kind() -> AsyncIterator[str]:
    """Уникальный kind на тест: реестр глобальный, а задачи из других тестов остаются в базе."""
    name = f"test.{uuid.uuid4().hex[:8]}"
    yield name
    unregister(name)


@pytest.fixture
def worker(kind: str) -> Worker:
    # Воркер видит только задачи своего теста: очередь в базе общая на прогон.
    return Worker(
        worker_id="w-test",
        poll_interval=0.01,
        heartbeat_s=0.05,
        shutdown_timeout_s=2,
        kinds=[kind, f"{kind}.unknown"],
    )


async def _status(job_id: uuid.UUID) -> Job:
    async with get_session_maker()() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        return job


# --- service ---------------------------------------------------------------


async def test_enqueue_dedupes_active_and_releases_finished_key(
    session: AsyncSession, kind: str
) -> None:
    first = await service.enqueue(session, kind, {"n": 1}, dedupe_key=f"{kind}:1")
    same = await service.enqueue(session, kind, {"n": 2}, dedupe_key=f"{kind}:1")
    await session.commit()
    assert same.id == first.id and same.payload == {"n": 1}
    assert first.status == JobStatus.queued and first.attempts == 0

    claimed = await service.claim_next(session, "w1", [kind])
    assert claimed is not None and claimed.id == first.id
    await service.complete(session, first.id, {"ok": True}, worker_id="w1")
    await session.commit()

    fresh = await service.enqueue(session, kind, {"n": 3}, dedupe_key=f"{kind}:1")
    await session.commit()
    assert fresh.id != first.id
    await session.refresh(first)
    assert first.dedupe_key is None and fresh.dedupe_key == f"{kind}:1"
    assert JobRead.model_validate(fresh).status == JobStatus.queued


async def test_claim_order_and_readiness(session: AsyncSession, kind: str) -> None:
    now = utcnow()
    late = await service.enqueue(session, kind, {"n": "late"}, run_after=now - timedelta(seconds=5))
    early = await service.enqueue(
        session, kind, {"n": "early"}, run_after=now - timedelta(seconds=10)
    )
    future = await service.enqueue(
        session, kind, {"n": "future"}, run_after=now + timedelta(hours=1)
    )
    await session.commit()

    first = await service.claim_next(session, "w1", [kind])
    assert first is not None and first.id == early.id
    assert first.status == JobStatus.running and first.locked_by == "w1" and first.attempts == 1
    assert aware(first.lease_until) > utcnow()
    assert first.started_at is not None
    second = await service.claim_next(session, "w1", [kind])
    assert second is not None and second.id == late.id
    assert await service.claim_next(session, "w1", [kind]) is None
    assert await service.claim_next(session, "w1", []) is None
    await session.commit()
    assert (await _status(future.id)).status == JobStatus.queued


async def test_claim_filters_by_kind(session: AsyncSession, kind: str) -> None:
    other = f"{kind}.other"
    await service.enqueue(session, other, {})
    mine = await service.enqueue(session, kind, {})
    await session.commit()
    claimed = await service.claim_next(session, "w1", [kind])
    assert claimed is not None and claimed.id == mine.id
    await session.commit()


async def test_expired_lease_is_reclaimed_as_zombie(session: AsyncSession, kind: str) -> None:
    job_ = await service.enqueue(session, kind, {}, max_attempts=3)
    await session.commit()
    claimed = await service.claim_next(session, "dead-worker", [kind])
    assert claimed is not None
    await session.commit()
    assert await service.claim_next(session, "w2", [kind]) is None  # аренда ещё жива

    await session.execute(
        update(Job).where(Job.id == job_.id).values(lease_until=utcnow() - timedelta(seconds=1))
    )
    await session.commit()
    zombie = await service.claim_next(session, "w2", [kind])
    assert zombie is not None and zombie.id == job_.id
    assert zombie.locked_by == "w2" and zombie.attempts == 2
    await session.commit()


async def test_zombie_without_attempts_left_becomes_failed(
    session: AsyncSession, kind: str
) -> None:
    job_ = await service.enqueue(session, kind, {}, max_attempts=1)
    await session.commit()
    assert await service.claim_next(session, "dead", [kind]) is not None
    await session.execute(
        update(Job).where(Job.id == job_.id).values(lease_until=utcnow() - timedelta(seconds=1))
    )
    await session.commit()
    assert await service.claim_next(session, "w2", [kind]) is None
    await session.commit()
    job_ = await _status(job_.id)
    assert job_.status == JobStatus.failed and "lease expired" in (job_.last_error or "")


def test_backoff_is_exponential_with_cap() -> None:
    assert [backoff_delay_s(n) for n in range(4)] == [5, 10, 20, 40]
    assert backoff_delay_s(7) == 600 and backoff_delay_s(20) == 600


async def test_fail_retries_then_fails_after_max_attempts(session: AsyncSession, kind: str) -> None:
    job_ = await service.enqueue(session, kind, {}, max_attempts=2)
    await session.commit()

    claimed = await service.claim_next(session, "w1", [kind])
    assert claimed is not None
    before = utcnow()
    failed_once = await service.fail(session, job_.id, "boom", worker_id="w1")
    await session.commit()
    assert failed_once.status == JobStatus.queued and failed_once.attempts == 1
    assert failed_once.last_error == "boom" and failed_once.locked_by is None
    delay = (aware(failed_once.run_after) - before).total_seconds()
    assert backoff_delay_s(1) - 1 <= delay <= backoff_delay_s(1) + 1

    assert await service.claim_next(session, "w1", [kind]) is None  # ждёт паузу
    await session.execute(update(Job).where(Job.id == job_.id).values(run_after=utcnow()))
    await session.commit()
    second = await service.claim_next(session, "w1", [kind])
    assert second is not None and second.attempts == 2
    final = await service.fail(session, job_.id, "boom again", worker_id="w1")
    await session.commit()
    assert final.status == JobStatus.failed and final.finished_at is not None

    retried = await service.retry(session, job_.id)
    await session.commit()
    assert retried.status == JobStatus.queued and retried.attempts == 0
    assert retried.finished_at is None and retried.last_error == "boom again"
    again = await service.claim_next(session, "w1", [kind])
    assert again is not None and again.id == job_.id
    await session.commit()
    with pytest.raises(ConflictError):
        await service.retry(session, job_.id)


async def test_fail_without_retry_and_owner_checks(session: AsyncSession, kind: str) -> None:
    job_ = await service.enqueue(session, kind, {})
    await session.commit()
    assert await service.claim_next(session, "w1", [kind]) is not None
    with pytest.raises(ConflictError, match="lease was lost"):
        await service.complete(session, job_.id, worker_id="w2")
    failed = await service.fail(session, job_.id, "unknown kind", retry=False, worker_id="w1")
    await session.commit()
    assert failed.status == JobStatus.failed and failed.attempts == 1
    with pytest.raises(ConflictError):
        await service.fail(session, job_.id, "again")


async def test_cancel_and_lookup(session: AsyncSession, kind: str) -> None:
    job_ = await service.enqueue(session, kind, {"x": 1})
    await session.commit()
    listed = await service.list_jobs(session, kind=kind)
    assert [item.id for item in listed] == [job_.id]
    assert (await service.get_job(session, job_.id)).payload == {"x": 1}
    cancelled = await service.cancel(session, job_.id)
    await session.commit()
    assert cancelled.status == JobStatus.cancelled
    assert await service.list_jobs(session, kind=kind, status=JobStatus.queued) == []
    with pytest.raises(ConflictError):
        await service.cancel(session, job_.id)
    with pytest.raises(NotFoundError):
        await service.get_job(session, uuid.uuid4())
    retried = await service.retry(session, job_.id)
    assert retried.status == JobStatus.queued
    await session.commit()


async def test_heartbeat_extends_lease_only_for_owner(session: AsyncSession, kind: str) -> None:
    job_ = await service.enqueue(session, kind, {})
    await session.commit()
    claimed = await service.claim_next(session, "w1", [kind], lease_s=1)
    assert claimed is not None
    await session.commit()
    old_lease = aware(claimed.lease_until)
    assert await service.heartbeat(session, job_.id, "w1", lease_s=120)
    await session.commit()
    await session.refresh(claimed)
    assert aware(claimed.lease_until) > old_lease + timedelta(seconds=60)
    assert not await service.heartbeat(session, job_.id, "impostor")
    await session.commit()


# --- worker ----------------------------------------------------------------


async def test_worker_runs_registered_job_end_to_end(
    session: AsyncSession, worker: Worker, kind: str
) -> None:
    seen: list[JobContext] = []

    @job(kind, resource="llm")
    async def handler(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        seen.append(ctx)
        assert await ctx.heartbeat()
        return {"echo": payload["text"].upper()}

    job_ = await service.enqueue(session, kind, {"text": "hello"})
    await session.commit()

    assert await worker.run_once() is True
    assert await worker.run_once() is False
    done = await _status(job_.id)
    assert done.status == JobStatus.succeeded
    assert done.result == {"echo": "HELLO"}
    assert done.locked_by is None and done.lease_until is None and done.finished_at is not None
    assert seen[0].kind == kind and seen[0].attempt == 1 and seen[0].worker_id == "w-test"
    assert worker._inflight == dict.fromkeys(worker.concurrency, 0)


async def test_builtin_ping_job(session: AsyncSession) -> None:
    load_all_handlers()
    assert "ping" in registered_kinds()
    worker = Worker(worker_id="w-ping", kinds=["ping"])
    job_ = await service.enqueue(session, "ping", {"message": "hi"})
    await session.commit()
    assert await worker.run_once()
    assert (await _status(job_.id)).result["pong"] == "hi"


async def test_unknown_kind_fails_without_retry(
    session: AsyncSession, worker: Worker, kind: str
) -> None:
    job_ = await service.enqueue(session, f"{kind}.unknown", {})
    await session.commit()
    assert await worker.run_once() is True
    failed = await _status(job_.id)
    assert failed.status == JobStatus.failed and failed.attempts == 1
    assert "no handler registered" in (failed.last_error or "")


async def test_handler_exception_requeues_with_backoff(
    session: AsyncSession, worker: Worker, kind: str
) -> None:
    @job(kind)
    async def handler(payload: dict[str, Any], ctx: JobContext) -> None:
        raise RuntimeError("ffmpeg exploded")

    job_ = await service.enqueue(session, kind, {})
    await session.commit()
    assert await worker.run_once()
    retried = await _status(job_.id)
    assert retried.status == JobStatus.queued and retried.attempts == 1
    assert retried.last_error == "RuntimeError: ffmpeg exploded"
    assert aware(retried.run_after) > utcnow() + timedelta(seconds=3)


async def test_graceful_stop_waits_for_running_job(
    session: AsyncSession, worker: Worker, kind: str
) -> None:
    gate = asyncio.Event()
    started = asyncio.Event()

    @job(kind)
    async def handler(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        started.set()
        await gate.wait()
        return {"done": True}

    job_ = await service.enqueue(session, kind, {})
    await session.commit()

    run_task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), timeout=5)
    worker.request_stop()
    await asyncio.sleep(0.1)
    assert not run_task.done()  # ждёт текущую задачу
    gate.set()
    await asyncio.wait_for(run_task, timeout=5)
    assert (await _status(job_.id)).status == JobStatus.succeeded


async def test_shutdown_timeout_releases_job_without_spending_attempt(
    session: AsyncSession, kind: str
) -> None:
    worker = Worker(
        worker_id="w-slow",
        poll_interval=0.01,
        heartbeat_s=0.05,
        shutdown_timeout_s=0.2,
        kinds=[kind],
    )
    started = asyncio.Event()

    @job(kind, resource="ffmpeg")
    async def handler(payload: dict[str, Any], ctx: JobContext) -> None:
        started.set()
        await asyncio.sleep(60)

    job_ = await service.enqueue(session, kind, {})
    await session.commit()
    run_task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), timeout=5)
    worker.request_stop()
    await asyncio.wait_for(run_task, timeout=5)
    released = await _status(job_.id)
    assert released.status == JobStatus.queued
    assert released.attempts == 0 and released.locked_by is None


async def test_lost_lease_cancels_handler(session: AsyncSession, worker: Worker, kind: str) -> None:
    cancelled = asyncio.Event()
    started = asyncio.Event()

    @job(kind)
    async def handler(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {}

    job_ = await service.enqueue(session, kind, {})
    await session.commit()
    run_task = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(started.wait(), timeout=5)
    # Другой воркер «отобрал» задачу: аренда истекла и он её захватил.
    await session.execute(update(Job).where(Job.id == job_.id).values(locked_by="w-other"))
    await session.commit()
    await asyncio.wait_for(run_task, timeout=5)
    assert cancelled.is_set()
    untouched = await _status(job_.id)
    assert untouched.status == JobStatus.running and untouched.locked_by == "w-other"


async def test_worker_respects_resource_capacity(session: AsyncSession, kind: str) -> None:
    worker = Worker(
        worker_id="w-cap",
        poll_interval=0.01,
        concurrency={"ffmpeg": 1, "default": 1},
        kinds=[kind],
    )
    release = asyncio.Event()
    running = 0
    peak = 0

    @job(kind, resource="ffmpeg")
    async def handler(payload: dict[str, Any], ctx: JobContext) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1

    for _ in range(3):
        await service.enqueue(session, kind, {})
    await session.commit()
    run_task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.3)
    assert peak == 1 and worker._inflight["ffmpeg"] == 1
    assert worker._claimable_kinds() == []
    release.set()
    await asyncio.sleep(0.3)
    worker.request_stop()
    await asyncio.wait_for(run_task, timeout=5)
    assert peak == 1
    rows = (await session.scalars(select(Job).where(Job.kind == kind))).all()
    assert {row.status for row in rows} == {JobStatus.succeeded}


def test_registry_rejects_duplicates_and_bad_resources(kind: str) -> None:
    @job(kind)
    async def one(payload, ctx):
        return None

    with pytest.raises(ValueError, match="already registered"):

        @job(kind)
        async def two(payload, ctx):
            return None

    with pytest.raises(ValueError, match="unknown resource"):
        job(f"{kind}.x", resource="gpu")
