"""Тестовая инфраструктура.

Каждый прогон получает собственную SQLite-базу во временном каталоге: схема
создаётся из метаданных моделей (быстро), а отдельный тест гоняет Alembic на
пустой базе, чтобы миграции не расходились с моделями.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

_TMP_DIR = Path(os.environ.get("PYTEST_TMP_ROOT", ".pytest_tmp")) / str(os.getpid())
_TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["MEDIA_ROOT"] = (_TMP_DIR / "media").as_posix()
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-1234")
# Тесты никогда не ходят в реальные модели, даже если в .env разработчика есть ключи.
os.environ["MODEL_PROVIDER"] = "fake"

from httpx import ASGITransport, AsyncClient  # noqa: E402

from leonit.ai.gateway import reset_gateway  # noqa: E402
from leonit.core.db import Base, dispose_engine, get_engine  # noqa: E402
from leonit.core.observability import metrics  # noqa: E402
from leonit.core.storage import reset_storage  # noqa: E402
from leonit.main import create_app  # noqa: E402
from leonit.models import load_all_models  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def _database_schema() -> AsyncIterator[None]:
    load_all_models()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Лимитеры живут в памяти процесса; тестовый клиент всегда с одного адреса."""
    from leonit.accounts.router import (
        login_rate_limiter,
        preview_rate_limiter,
        register_rate_limiter,
    )
    from leonit.candidates.router import public_rate_limiter

    limiters = (
        login_rate_limiter,
        register_rate_limiter,
        preview_rate_limiter,
        public_rate_limiter,
    )
    for limiter in limiters:
        limiter.clear()
    yield
    for limiter in limiters:
        limiter.clear()


@pytest.fixture(autouse=True)
def _reset_gateway_and_storage():
    # Провайдеры и HTTP-клиенты кэшируются по конфигурации; между тестами
    # event loop меняется, поэтому кэш сбрасываем, а не переиспользуем.
    reset_gateway()
    reset_storage()
    yield
    reset_gateway()
    reset_storage()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
