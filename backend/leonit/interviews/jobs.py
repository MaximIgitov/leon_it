"""Обработчики задач интервью.

Реальная обработка (извлечение аудио, транскрибация, оценка) подключается в
следующих шагах; сейчас задачи регистрируются, чтобы завершение ответа и
интервью уже ставило их в очередь, а воркер не падал на неизвестном виде.
"""

from __future__ import annotations

from leonit.interviews.service import ANSWER_PROCESS_JOB, INTERVIEW_PROCESS_JOB
from leonit.jobs.registry import JobContext, job


@job(ANSWER_PROCESS_JOB, resource="ffmpeg")
async def process_answer(payload: dict, ctx: JobContext) -> dict | None:
    return {"skipped": "media pipeline is not wired yet", "answer_id": payload.get("answer_id")}


@job(INTERVIEW_PROCESS_JOB, resource="llm")
async def process_interview(payload: dict, ctx: JobContext) -> dict | None:
    return {
        "skipped": "evaluation pipeline is not wired yet",
        "interview_id": payload.get("interview_id"),
    }
