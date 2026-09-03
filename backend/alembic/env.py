from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from leonit.core.config import get_settings
from leonit.core.db import Base
from leonit.models import load_all_models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Явный -x url=... или sqlalchemy.url из ini имеют приоритет над настройками:
# так тесты гоняют миграции на отдельной базе.
database_url = context.get_x_argument(as_dictionary=True).get("url") or (
    config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL
)
config.set_main_option("sqlalchemy.url", database_url)
load_all_models()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # render_as_batch: SQLite не умеет ALTER TABLE, batch-режим переписывает
    # таблицу целиком и делает одну и ту же миграцию рабочей на обоих движках.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
