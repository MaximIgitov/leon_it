"""Встроенные задачи: проверка, что воркер жив и очередь работает насквозь."""

from __future__ import annotations

from typing import Any

from leonit.jobs.registry import JobContext, job


@job("ping")
async def ping(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    return {"pong": payload.get("message", "pong"), "attempt": ctx.attempt, "worker": ctx.worker_id}
