"""Очередь задач в базе.

Очередь в той же PostgreSQL, а не в отдельном брокере: постановка задачи
попадает в одну транзакцию с изменением домена (кандидат завершил интервью →
задача на обработку), и ничего не теряется между двумя системами. Захват через
``FOR UPDATE SKIP LOCKED`` и аренду (``lease_until``) позволяет нескольким
воркерам работать без координатора, а упавший воркер не блокирует задачу.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk
from leonit.core.time import utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}
)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id = uuid_pk()
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            native_enum=False,
            length=16,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=JobStatus.queued,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # Уникальность — гарантия «не больше одной активной задачи на сущность»;
    # завершённая задача освобождает ключ (см. service.enqueue).
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def __repr__(self) -> str:
        return f"<Job {self.kind} {self.id} {self.status}>"
