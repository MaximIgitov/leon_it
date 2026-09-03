"""Обработчики задач интервью.

Обработка ответа (извлечение аудио, транскрибация) подключается медиа-пайплайном;
сейчас задача регистрируется, чтобы завершение ответа уже ставило её в очередь,
а воркер не падал на неизвестном виде. Оценка интервью (``interview.process``)
живёт в ``leonit.evaluation.jobs``.
"""

from __future__ import annotations

from leonit.interviews.service import ANSWER_PROCESS_JOB
from leonit.jobs.registry import JobContext, job


@job(ANSWER_PROCESS_JOB, resource="ffmpeg")
async def process_answer(payload: dict, ctx: JobContext) -> dict | None:
    return {"skipped": "media pipeline is not wired yet", "answer_id": payload.get("answer_id")}
