"""Обработчики задач интервью.

Обработка ответа (``answer.process``) живёт в ``leonit.pipeline.jobs``; здесь
остаётся оценка интервью целиком: она подключается следующим шагом, а задача
регистрируется уже сейчас, чтобы завершение интервью ставило её в очередь и
воркер не падал на неизвестном виде.
"""

from __future__ import annotations

from leonit.interviews.service import INTERVIEW_PROCESS_JOB
from leonit.jobs.registry import JobContext, job


@job(INTERVIEW_PROCESS_JOB, resource="llm")
async def process_interview(payload: dict, ctx: JobContext) -> dict | None:
    return {
        "skipped": "evaluation pipeline is not wired yet",
        "interview_id": payload.get("interview_id"),
    }
