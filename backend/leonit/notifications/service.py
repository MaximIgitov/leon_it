from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.core.authz import Actor, authorize
from leonit.core.errors import NotFoundError
from leonit.core.time import utcnow
from leonit.jobs import service as jobs
from leonit.notifications.models import EmailMessage, EmailStatus
from leonit.notifications.sender import get_email_sender

EMAIL_JOB_KIND = "email.send"


async def queue_email(
    session: AsyncSession,
    *,
    organization_id: UUID | None,
    to_email: str,
    subject: str,
    body_text: str,
    kind: str,
    interview_id: UUID | None = None,
) -> EmailMessage:
    """Положить письмо в outbox и поставить задачу на отправку (без commit)."""
    message = EmailMessage(
        organization_id=organization_id,
        interview_id=interview_id,
        kind=kind,
        to_email=to_email.lower(),
        subject=subject,
        body_text=body_text,
    )
    session.add(message)
    await session.flush()
    await jobs.enqueue(
        session,
        EMAIL_JOB_KIND,
        {"email_id": str(message.id)},
        dedupe_key=f"email:{message.id}",
        max_attempts=5,
    )
    return message


async def deliver_email(session: AsyncSession, email_id: UUID) -> EmailMessage:
    """Отправить письмо из outbox (вызывается обработчиком задачи)."""
    message = await session.get(EmailMessage, email_id)
    if message is None:
        raise NotFoundError("Письмо не найдено")
    if message.status == EmailStatus.sent:
        return message
    sender = get_email_sender()
    try:
        await sender.send(
            to_email=message.to_email, subject=message.subject, body_text=message.body_text
        )
    except Exception as error:
        message.status = EmailStatus.failed
        message.error = str(error)[:2000]
        message.provider = sender.name
        await session.commit()
        raise
    message.status = EmailStatus.sent
    message.provider = sender.name
    message.error = None
    message.sent_at = utcnow()
    await session.commit()
    return message


async def list_emails(session: AsyncSession, actor: Actor, limit: int = 100) -> list[EmailMessage]:
    authorize(actor, "org.read")
    rows = await session.scalars(
        select(EmailMessage)
        .where(EmailMessage.organization_id == actor.organization_id)
        .order_by(EmailMessage.created_at.desc())
        .limit(limit)
    )
    return list(rows)
