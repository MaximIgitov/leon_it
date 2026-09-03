"""Воркер фоновых задач.

Цикл: захватить задачу → запустить обработчик отдельной asyncio-задачей под
семафором ресурса → продлевать аренду, пока он работает → записать результат.
Остановка по SIGTERM/SIGINT graceful: новые задачи не берутся, текущие
дорабатывают до ``shutdown_timeout_s``, остальные возвращаются в очередь без
потери попытки. Запуск: ``python -m leonit.jobs.worker``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leonit.ai.gateway import shutdown_gateway
from leonit.core.db import dispose_engine, get_session_maker
from leonit.core.logging import setup_logging
from leonit.jobs import service
from leonit.jobs.models import Job
from leonit.jobs.registry import (
    JobContext,
    JobHandler,
    get_handler,
    load_all_handlers,
    registered_kinds,
    resource_for,
    startup_hooks,
    tick_hooks,
)
from leonit.models import load_all_models

# Имя задано явно: при запуске через ``python -m`` модуль называется ``__main__``.
log = logging.getLogger("leonit.jobs.worker")

DEFAULT_CONCURRENCY: dict[str, int] = {"ffmpeg": 1, "llm": 3, "default": 4}


class Worker:
    def __init__(
        self,
        *,
        worker_id: str | None = None,
        poll_interval: float = 1.0,
        lease_s: int = service.DEFAULT_LEASE_S,
        heartbeat_s: float = 15.0,
        concurrency: dict[str, int] | None = None,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
        shutdown_timeout_s: float = 60.0,
        tick_interval_s: float = 3600.0,
        kinds: Sequence[str] | None = None,
    ) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.poll_interval = poll_interval
        self.lease_s = lease_s
        self.heartbeat_s = heartbeat_s
        self.shutdown_timeout_s = shutdown_timeout_s
        self.tick_interval_s = tick_interval_s
        # Ограничение видов задач: отдельный пул воркеров под тяжёлые задачи или
        # изоляция в тестах. None — брать любые, в том числе незарегистрированные.
        self.kinds = list(kinds) if kinds is not None else None
        self.concurrency = dict(concurrency or DEFAULT_CONCURRENCY)
        self.concurrency.setdefault("default", 1)
        self._session_maker = session_maker
        self._semaphores = {name: asyncio.Semaphore(n) for name, n in self.concurrency.items()}
        self._inflight: dict[str, int] = dict.fromkeys(self.concurrency, 0)
        self._tasks: set[asyncio.Task[None]] = set()
        self._lost_leases: set[uuid.UUID] = set()
        self._stop = asyncio.Event()

    # --- публичный API ------------------------------------------------------

    @property
    def session_maker(self) -> async_sessionmaker[AsyncSession]:
        if self._session_maker is None:
            self._session_maker = get_session_maker()
        return self._session_maker

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    async def run_startup_hooks(self) -> None:
        """Выполнить хуки старта; сбой одного (например, базы) не останавливает воркер."""
        for hook in startup_hooks():
            try:
                await hook(self.session_maker)
            except Exception:
                name = getattr(hook, "__name__", repr(hook))
                log.exception("worker %s: startup hook %s failed", self.worker_id, name)

    async def run_tick_hooks(self) -> None:
        """Выполнить периодические хуки; сбой одного не мешает остальным и воркеру."""
        for hook in tick_hooks():
            try:
                await hook(self.session_maker)
            except Exception:
                name = getattr(hook, "__name__", repr(hook))
                log.exception("worker %s: tick hook %s failed", self.worker_id, name)

    async def run_once(self) -> bool:
        """Захватить и обработать одну задачу до конца; False — очередь пуста."""
        job = await self._claim()
        if job is None:
            return False
        resource = self._reserve(job)
        await self._execute(job, resource)
        return True

    async def run(self) -> None:
        self._install_signal_handlers()
        log.info("worker %s started, concurrency=%s", self.worker_id, self.concurrency)
        last_tick = time.monotonic()
        try:
            while not self.stopping:
                if time.monotonic() - last_tick >= self.tick_interval_s:
                    last_tick = time.monotonic()
                    await self.run_tick_hooks()
                job = await self._claim()
                if job is None:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
                    continue
                resource = self._reserve(job)
                task = asyncio.create_task(self._execute(job, resource), name=f"job-{job.id}")
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        finally:
            await self._drain()
            log.info("worker %s stopped", self.worker_id)

    # --- захват -------------------------------------------------------------

    def _claimable_kinds(self) -> list[str] | None:
        """None — брать любую задачу; [] — свободных слотов нет."""
        free = {name for name, limit in self.concurrency.items() if self._inflight[name] < limit}
        if not free:
            return []
        if free == set(self.concurrency):
            return self.kinds
        candidates = self.kinds if self.kinds is not None else registered_kinds()
        return [kind for kind in candidates if self._resource(kind) in free]

    async def _claim(self) -> Job | None:
        kinds = self._claimable_kinds()
        if kinds is not None and not kinds:
            return None
        try:
            async with self.session_maker() as session, session.begin():
                return await service.claim_next(
                    session, self.worker_id, kinds, lease_s=self.lease_s
                )
        except Exception:
            log.exception("worker %s: claim failed", self.worker_id)
            return None

    def _resource(self, kind: str) -> str:
        resource = resource_for(kind)
        return resource if resource in self._semaphores else "default"

    def _reserve(self, job: Job) -> str:
        # Счётчик растёт до запуска задачи, иначе цикл успеет захватить ещё
        # одну задачу того же ресурса, пока первая ждёт семафор.
        resource = self._resource(job.kind)
        self._inflight[resource] += 1
        return resource

    # --- выполнение ---------------------------------------------------------

    async def _execute(self, job: Job, resource: str) -> None:
        try:
            handler = get_handler(job.kind)
            if handler is None:
                log.error("job %s: no handler for kind %r", job.id, job.kind)
                await self._fail(job, f"no handler registered for kind {job.kind!r}", retry=False)
                return
            async with self._semaphores[resource]:
                await self._run_handler(job, handler)
        finally:
            self._inflight[resource] -= 1

    async def _run_handler(self, job: Job, handler: JobHandler) -> None:
        context = JobContext(
            job_id=job.id,
            kind=job.kind,
            attempt=job.attempts,
            worker_id=self.worker_id,
            session_maker=self.session_maker,
            _heartbeat=lambda: self._heartbeat(job.id),
        )
        log.info("job %s kind=%s attempt=%s started", job.id, job.kind, job.attempts)
        try:
            handler_task = asyncio.create_task(handler.func(dict(job.payload), context))
        except Exception as error:
            # Обработчик даже не стартовал (не та сигнатура, реестр обошли и
            # подсунули обычную функцию): это баг кода, повтор не поможет, а
            # без записи результата задача висела бы в running до конца аренды.
            log.exception("job %s kind=%s could not start handler", job.id, job.kind)
            await self._fail(job, f"{type(error).__name__}: {error}", retry=False)
            return
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job.id, handler_task))
        try:
            try:
                result = await handler_task
            finally:
                # Heartbeat останавливается до записи результата: тик между
                # коммитом «succeeded» и отменой увидел бы задачу не running,
                # счёл аренду потерянной и навсегда оставил id в _lost_leases.
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
        except asyncio.CancelledError:
            if job.id in self._lost_leases:
                log.warning("job %s: lease lost, another worker took it over", job.id)
                return
            # Остановка воркера: вернуть задачу в очередь и продолжить отмену.
            await self._release(job)
            raise
        except Exception as error:
            log.exception("job %s kind=%s failed", job.id, job.kind)
            await self._fail(job, f"{type(error).__name__}: {error}")
        else:
            await self._complete(job, result)
            log.info("job %s kind=%s succeeded", job.id, job.kind)
        finally:
            self._lost_leases.discard(job.id)

    async def _heartbeat_loop(self, job_id: uuid.UUID, handler_task: asyncio.Task[Any]) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_s)
            if not await self._heartbeat(job_id):
                self._lost_leases.add(job_id)
                handler_task.cancel()
                return

    async def _heartbeat(self, job_id: uuid.UUID) -> bool:
        try:
            async with self.session_maker() as session, session.begin():
                return await service.heartbeat(
                    session, job_id, self.worker_id, lease_s=self.lease_s
                )
        except Exception:
            # Сбой базы на heartbeat — не повод убивать обработчик; аренда
            # продлится на следующем тике или задачу подберут как зомби.
            log.exception("job %s: heartbeat failed", job_id)
            return True

    async def _complete(self, job: Job, result: dict[str, Any] | None) -> None:
        if result is not None and not isinstance(result, dict):
            result = {"value": result}
        try:
            async with self.session_maker() as session, session.begin():
                await service.complete(session, job.id, result, worker_id=self.worker_id)
        except Exception:
            log.exception("job %s: could not record completion", job.id)

    async def _fail(self, job: Job, error: str, *, retry: bool = True) -> None:
        try:
            async with self.session_maker() as session, session.begin():
                await service.fail(session, job.id, error, retry=retry, worker_id=self.worker_id)
        except Exception:
            log.exception("job %s: could not record failure", job.id)

    async def _release(self, job: Job) -> None:
        try:
            async with self.session_maker() as session, session.begin():
                await service.release(session, job.id, self.worker_id)
        except Exception:
            log.exception("job %s: could not release", job.id)

    # --- остановка ----------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, self.request_stop)
            except (NotImplementedError, RuntimeError):
                # Windows: add_signal_handler недоступен, ставим обычный обработчик.
                signal.signal(signum, lambda *_: loop.call_soon_threadsafe(self.request_stop))

    async def _drain(self) -> None:
        if not self._tasks:
            return
        log.info("worker %s: waiting for %s running job(s)", self.worker_id, len(self._tasks))
        _done, pending = await asyncio.wait(set(self._tasks), timeout=self.shutdown_timeout_s)
        for task in pending:
            task.cancel()
        if pending:
            log.warning("worker %s: %s job(s) returned to queue", self.worker_id, len(pending))
            await asyncio.gather(*pending, return_exceptions=True)


async def _serve(worker: Worker, *, once: bool) -> None:
    try:
        await worker.run_startup_hooks()
        await worker.run_tick_hooks()
        if once:
            while await worker.run_once():
                pass
        else:
            await worker.run()
    finally:
        await shutdown_gateway()
        await dispose_engine()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LeonIT jobs worker")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--once", action="store_true", help="обработать очередь и выйти")
    args = parser.parse_args(argv)

    setup_logging()
    load_all_models()
    load_all_handlers()
    worker = Worker(worker_id=args.worker_id, poll_interval=args.poll_interval)
    asyncio.run(_serve(worker, once=args.once))


if __name__ == "__main__":
    main()
