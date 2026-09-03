from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from leonit.accounts.deps import CurrentActor
from leonit.candidates.router import _client_ip, interview_out, public_rate_limiter
from leonit.candidates.schemas import InterviewOut
from leonit.core.deps import DbSession
from leonit.core.time import aware
from leonit.reports.models import ReportShare, ReviewNote
from leonit.reports.schemas import (
    DecisionIn,
    NoteIn,
    NoteOut,
    PublicReport,
    ShareCreate,
    ShareOut,
    ShareViewOut,
)
from leonit.reports.service import ReportService, share_status, share_url
from leonit.vacancies.models import Vacancy

router = APIRouter(prefix="/interviews", tags=["reports"])
public_router = APIRouter(prefix="/public/reports", tags=["public"])


def note_out(note: ReviewNote) -> NoteOut:
    return NoteOut(
        id=str(note.id),
        author_user_id=str(note.author_user_id) if note.author_user_id else None,
        author_label=note.author_label,
        text=note.text,
        answer_id=str(note.answer_id) if note.answer_id else None,
        at_s=note.at_s,
        created_at=aware(note.created_at),  # type: ignore[arg-type]
    )


def share_out(share: ReportShare, token: str | None = None) -> ShareOut:
    return ShareOut(
        id=str(share.id),
        label=share.label,
        expires_at=aware(share.expires_at),  # type: ignore[arg-type]
        revoked_at=aware(share.revoked_at),
        include_integrity=share.include_integrity,
        allow_download=share.allow_download,
        view_count=share.view_count,
        last_viewed_at=aware(share.last_viewed_at),
        created_at=aware(share.created_at),  # type: ignore[arg-type]
        status=share_status(share),  # type: ignore[arg-type]
        url=share_url(token) if token else None,
    )


async def _title(session, vacancy_id: UUID) -> str:
    vacancy = await session.get(Vacancy, vacancy_id)
    return vacancy.title if vacancy else ""


@router.post("/{interview_id}/decision", response_model=InterviewOut)
async def decide(
    interview_id: UUID, payload: DecisionIn, actor: CurrentActor, session: DbSession
) -> InterviewOut:
    interview = await ReportService(session).decide(actor, interview_id, payload)
    return interview_out(interview, await _title(session, interview.vacancy_id))


@router.get("/{interview_id}/notes", response_model=list[NoteOut])
async def list_notes(interview_id: UUID, actor: CurrentActor, session: DbSession) -> list[NoteOut]:
    return [note_out(n) for n in await ReportService(session).list_notes(actor, interview_id)]


@router.post("/{interview_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def add_note(
    interview_id: UUID, payload: NoteIn, actor: CurrentActor, session: DbSession
) -> NoteOut:
    return note_out(await ReportService(session).add_note(actor, interview_id, payload))


@router.delete("/{interview_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    interview_id: UUID, note_id: UUID, actor: CurrentActor, session: DbSession
) -> None:
    await ReportService(session).delete_note(actor, interview_id, note_id)


@router.get("/{interview_id}/shares", response_model=list[ShareOut])
async def list_shares(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> list[ShareOut]:
    return [share_out(s) for s in await ReportService(session).list_shares(actor, interview_id)]


@router.post("/{interview_id}/shares", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
async def create_share(
    interview_id: UUID, payload: ShareCreate, actor: CurrentActor, session: DbSession
) -> ShareOut:
    share, token = await ReportService(session).create_share(actor, interview_id, payload)
    return share_out(share, token)


@router.delete("/{interview_id}/shares/{share_id}", response_model=ShareOut)
async def revoke_share(
    interview_id: UUID, share_id: UUID, actor: CurrentActor, session: DbSession
) -> ShareOut:
    return share_out(await ReportService(session).revoke_share(actor, interview_id, share_id))


@router.post("/{interview_id}/shares/{share_id}/extend", response_model=ShareOut)
async def extend_share(
    interview_id: UUID, share_id: UUID, actor: CurrentActor, session: DbSession, days: int = 14
) -> ShareOut:
    days = max(1, min(days, 90))
    return share_out(await ReportService(session).extend_share(actor, interview_id, share_id, days))


@router.get("/{interview_id}/shares/views", response_model=list[ShareViewOut])
async def share_views(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> list[ShareViewOut]:
    return [
        ShareViewOut(
            what=v.what,
            ip=v.ip,
            user_agent=v.user_agent,
            created_at=aware(v.created_at),  # type: ignore[arg-type]
        )
        for v in await ReportService(session).share_views(actor, interview_id)
    ]


# ---------------------------------------------------------------------- public


def _limit(request: Request) -> None:
    decision = public_rate_limiter.check(_client_ip(request))
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="Слишком много запросов, попробуйте позже")


@public_router.get("/{token}", response_model=PublicReport)
async def public_report(token: str, session: DbSession, request: Request) -> PublicReport:
    _limit(request)
    data = await ReportService(session).public_report(
        token, ip=_client_ip(request), user_agent=request.headers.get("user-agent")
    )
    data["notes"] = [note_out(n) for n in data["notes"]]
    return PublicReport(**data)


@public_router.post("/{token}/decision", status_code=status.HTTP_204_NO_CONTENT)
async def public_decide(
    token: str, payload: DecisionIn, session: DbSession, request: Request
) -> None:
    _limit(request)
    await ReportService(session).public_decide(token, payload, ip=_client_ip(request))


@public_router.post("/{token}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def public_note(token: str, payload: NoteIn, session: DbSession, request: Request) -> NoteOut:
    _limit(request)
    return note_out(await ReportService(session).public_note(token, payload))
