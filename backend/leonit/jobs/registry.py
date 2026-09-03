"""Реестр обработчиков задач.

Обработчик привязан к ресурсу (``llm``, ``ffmpeg``, ``default``): воркер
ограничивает параллелизм по ресурсу, а не по задаче — один ffmpeg занимает всё
CPU, а лишние параллельные запросы к моделям упираются в rate limit.
"""

from __future__ import annotations

import importlib
import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Resource = Literal["llm", "ffmpeg", "default"]
RESOURCES: tuple[Resource, ...] = ("llm", "ffmpeg", "default")

# Модули, регистрирующие обработчики; воркер импортирует их на старте
# (аналог MODEL_MODULES в leonit.models).
JOB_HANDLER_MODULES: tuple[str, ...] = (
    "leonit.jobs.builtin",
    "leonit.notifications.jobs",
    "leonit.evaluation.jobs",
    "leonit.pipeline.jobs",
    "leonit.hh.jobs",
)


@dataclass(slots=True)
class JobContext:
    job_id: uuid.UUID
    kind: str
    attempt: int
    worker_id: str
    session_maker: async_sessionmaker[AsyncSession]
    _heartbeat: Callable[[], Awaitable[bool]]

    async def heartbeat(self) -> bool:
        """Продлить аренду вручную (долгий шаг без await). False — задача отобрана."""
        return await self._heartbeat()


Handler = Callable[[dict[str, Any], JobContext], Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True, slots=True)
class JobHandler:
    kind: str
    resource: Resource
    func: Handler


_registry: dict[str, JobHandler] = {}


def job(kind: str, *, resource: Resource = "default", replace: bool = False):
    if resource not in RESOURCES:
        raise ValueError(f"unknown resource {resource!r}; expected one of {RESOURCES}")

    def decorator(func: Handler) -> Handler:
        # Обычная функция вместо coroutine — ошибка на импорте модуля, а не
        # TypeError в воркере, из-за которого задача зависала бы в running до
        # истечения аренды.
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"job handler for {kind!r} must be an async function, got {func!r}")
        existing = _registry.get(kind)
        if existing is not None and existing.func is not func and not replace:
            raise ValueError(f"job kind {kind!r} is already registered")
        _registry[kind] = JobHandler(kind=kind, resource=resource, func=func)
        return func

    return decorator


def get_handler(kind: str) -> JobHandler | None:
    return _registry.get(kind)


def registered_kinds() -> list[str]:
    return sorted(_registry)


def resource_for(kind: str) -> Resource:
    handler = _registry.get(kind)
    return handler.resource if handler else "default"


def unregister(kind: str) -> None:
    _registry.pop(kind, None)


def load_all_handlers() -> None:
    for module in JOB_HANDLER_MODULES:
        importlib.import_module(module)


# Действия при старте воркера (поставить периодическую задачу и т. п.).
# Регистрируются теми же модулями, что и обработчики, поэтому воркер ничего не
# знает о предметных областях — они сами говорят, что нужно сделать на старте.
StartupHook = Callable[[async_sessionmaker[AsyncSession]], Awaitable[None]]
_startup_hooks: list[StartupHook] = []


def on_worker_start(func: StartupHook) -> StartupHook:
    if func not in _startup_hooks:
        _startup_hooks.append(func)
    return func


def startup_hooks() -> list[StartupHook]:
    return list(_startup_hooks)


# Периодические действия воркера (раз в ``Worker.tick_interval_s``, впервые —
# сразу после хуков старта): страховка расписаний, возврат брошенных сущностей
# в очередь. В отличие от самопланирующихся задач, тик не зависит от того,
# успешно ли выполнилась предыдущая итерация.
TickHook = StartupHook
_tick_hooks: list[TickHook] = []


def on_worker_tick(func: TickHook) -> TickHook:
    if func not in _tick_hooks:
        _tick_hooks.append(func)
    return func


def tick_hooks() -> list[TickHook]:
    return list(_tick_hooks)
