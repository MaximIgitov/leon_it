from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from leonit.accounts.deps import CurrentActor
from leonit.core.deps import DbSession
from leonit.core.time import aware
from leonit.notifications.service import list_emails

router = APIRouter(prefix="/organization/emails", tags=["organization"])


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
