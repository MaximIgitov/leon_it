"""Представление задачи для UI (статус обработки в карточке кандидата)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from leonit.jobs.models import JobStatus


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: JobStatus
    attempts: int
    max_attempts: int
    run_after: datetime
    lease_until: datetime | None
    locked_by: str | None
    last_error: str | None
    result: dict[str, Any] | None
    dedupe_key: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
