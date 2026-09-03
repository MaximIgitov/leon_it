"""Задача ``huntflow.push``: передача кандидата в Huntflow из очереди.

Ресурс ``default``: это короткие HTTP-вызовы. Повторы делает очередь —
обработчик пробрасывает только сетевые сбои, а отклонённый токен и ответы
4xx завершают задачу с ошибкой в строке соискателя (см. ``service.perform_push``).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from leonit.huntflow.service import PUSH_JOB, perform_push
from leonit.jobs.registry import JobContext, job


@job(PUSH_JOB, resource="default")
async def push_candidate_job(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any] | None:
    async with ctx.session_maker() as session:
        return await perform_push(session, UUID(str(payload["huntflow_applicant_id"])))
