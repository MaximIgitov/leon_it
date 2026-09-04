from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from leonit.accounts.deps import CurrentActor
from leonit.candidates.models import Candidate, ConsentRecord, Interview
from leonit.core.deps import DbSession
from leonit.core.errors import NotFoundError
from leonit.core.time import aware, utcnow
from leonit.notifications.service import list_emails
from leonit.notifications.unsubscribe import verify_unsubscribe_token

router = APIRouter(prefix="/organization/emails", tags=["organization"])
public_router = APIRouter(prefix="/public/unsubscribe", tags=["public"])


class EmailOut(BaseModel):
    id: str
    kind: str
    to_email: str
    subject: str
    body_text: str
    status: str
    provider: str | None
    error: str | None
    sent_at: datetime | None
    created_at: datetime
    interview_id: str | None


@router.get("", response_model=list[EmailOut])
async def list_organization_emails(actor: CurrentActor, session: DbSession) -> list[EmailOut]:
    rows = await list_emails(session, actor)
    return [
        EmailOut(
            id=str(row.id),
            kind=row.kind,
            to_email=row.to_email,
            subject=row.subject,
            body_text=row.body_text,
            status=row.status.value,
            provider=row.provider,
            error=row.error,
            sent_at=aware(row.sent_at),
            created_at=aware(row.created_at),  # type: ignore[arg-type]
            interview_id=str(row.interview_id) if row.interview_id else None,
        )
        for row in rows
    ]


class UnsubscribeOut(BaseModel):
    """Ответ страницы отписки: без имени и e-mail — ссылка может уйти кому угодно."""

    already: bool


@public_router.post("/{token}", response_model=UnsubscribeOut)
async def unsubscribe(token: str, session: DbSession) -> UnsubscribeOut:
    """Отписать кандидата от писем LeonIT по подписанной ссылке из письма."""
    candidate_id = verify_unsubscribe_token(token)
    if candidate_id is None:
        raise NotFoundError("Ссылка недействительна или устарела")
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFoundError("Ссылка недействительна или устарела")
    if candidate.unsubscribed_at is not None:
        return UnsubscribeOut(already=True)
    candidate.unsubscribed_at = utcnow()
    candidate.newsletter_opt_in = False
    # Отказ виден там же, где само согласие: в журнале по последнему интервью.
    interview_id = await session.scalar(
        select(Interview.id)
        .where(Interview.candidate_id == candidate.id)
        .order_by(Interview.invited_at.desc())
        .limit(1)
    )
    if interview_id is not None:
        session.add(
            ConsentRecord(
                organization_id=candidate.organization_id,
                interview_id=interview_id,
                candidate_id=candidate.id,
                slug="newsletter-consent",
                version="unsubscribe",
                document_hash="",
                accepted=False,
                ip=None,
                user_agent=None,
                created_at=utcnow(),
            )
        )
    await session.commit()
    return UnsubscribeOut(already=False)
