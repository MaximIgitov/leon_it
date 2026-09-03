"""Подключение к базе и общие строительные блоки моделей.

Движок создаётся лениво по текущим настройкам: тесты подменяют `DATABASE_URL`
до первого обращения и получают собственную SQLite-базу без монкипатчинга.
Один и тот же код работает на SQLite (локально, в тестах) и PostgreSQL (стенд).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, Uuid, event
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from leonit.core.config import get_settings
from leonit.core.time import utcnow


class Base(AsyncAttrs, DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    # SQLite не проверяет внешние ключи по умолчанию; в тестах это прятало бы
    # ошибки каскадного удаления, которые на PostgreSQL проявятся сразу.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        _enable_sqlite_foreign_keys(engine)
    return engine


@lru_cache
def get_session_maker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_maker()() as session:
        yield session


async def dispose_engine() -> None:
    """Закрыть пул соединений (lifespan приложения и тесты)."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_session_maker.cache_clear()
