from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leonit.core.logging import get_logger
from leonit.jobs.registry import JobContext, job, on_worker_tick
from leonit.notifications.outreach import (
    FEEDBACK_JOB,
    REMINDER_JOB,
    schedule_reminders,
    send_candidate_feedback,
    send_reminder,
)
from leonit.notifications.service import EMAIL_JOB_KIND, deliver_email

log = get_logger(__name__)


@job(EMAIL_JOB_KIND, resource="default")
async def send_email_job(payload: dict, ctx: JobContext) -> dict | None:
    async with ctx.session_maker() as session:
        message = await deliver_email(session, UUID(payload["email_id"]))
        return {"status": message.status.value, "provider": message.provider}


@job(REMINDER_JOB, resource="default")
async def send_reminder_job(payload: dict, ctx: JobContext) -> dict | None:
    async with ctx.session_maker() as session:
        return await send_reminder(session, UUID(payload["interview_id"]))


@job(FEEDBACK_JOB, resource="default")
async def send_candidate_feedback_job(payload: dict, ctx: JobContext) -> dict | None:
    async with ctx.session_maker() as session:
        return await send_candidate_feedback(session, UUID(payload["interview_id"]))


@on_worker_tick
async def schedule_reminders_tick(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Раз в час: интервью, у которых ссылка истекает в ближайшие двое суток."""
    async with session_maker() as session:
        queued = await schedule_reminders(session)
        if queued:
            log.info("reminder.scheduled count=%s", queued)
