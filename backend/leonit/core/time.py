from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """SQLite возвращает наивные даты; приводим их к UTC для сравнения."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
