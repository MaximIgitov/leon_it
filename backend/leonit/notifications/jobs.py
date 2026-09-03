from __future__ import annotations

from uuid import UUID

from leonit.jobs.registry import JobContext, job
from leonit.notifications.service import EMAIL_JOB_KIND, deliver_email


@job(EMAIL_JOB_KIND, resource="default")
async def send_email_job(payload: dict, ctx: JobContext) -> dict | None:
    async with ctx.session_maker() as session:
        message = await deliver_email(session, UUID(payload["email_id"]))
        return {"status": message.status.value, "provider": message.provider}
