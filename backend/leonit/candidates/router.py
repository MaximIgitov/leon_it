from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from leonit.accounts.deps import CurrentActor
from leonit.accounts.models import Organization
from leonit.candidates.models import Candidate, Interview, InterviewStatus
from leonit.candidates.schemas import (
    BulkCreateResult,
    CandidateBulkCreate,
    CandidateCreate,
    CandidateOut,
    CandidateUpdate,
    ConsentDocumentOut,
    ConsentSubmit,
    InterviewOut,
    InvitationPublicOut,
    InviteRequest,
)
from leonit.candidates.service import (
    CandidateService,
    InterviewService,
    estimated_minutes,
    interview_link,
    vacancy_titles,
)
from leonit.core.deps import DbSession
from leonit.core.rate_limit import SlidingWindowRateLimiter
from leonit.core.time import aware
from leonit.legal.service import consent_documents
from leonit.vacancies.models import Vacancy

candidates_router = APIRouter(prefix="/candidates", tags=["candidates"])
interviews_router = APIRouter(prefix="/interviews", tags=["interviews"])
public_router = APIRouter(prefix="/public/invitations", tags=["public"])

public_rate_limiter = SlidingWindowRateLimiter(max_attempts=120, window_s=300)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def candidate_out(candidate: Candidate) -> CandidateOut:
    interviews = sorted(candidate.interviews, key=lambda i: i.invited_at, reverse=True)
    return CandidateOut(
        id=str(candidate.id),
        full_name=candidate.full_name,
        email=candidate.email,
        phone=candidate.phone,
        source=candidate.source.value,  # type: ignore[arg-type]
        notes=candidate.notes,
        has_resume=bool(candidate.resume_key),
        newsletter_opt_in=candidate.newsletter_opt_in,
        external_ref=candidate.external_ref,
        created_at=aware(candidate.created_at),  # type: ignore[arg-type]
        interview_count=len(interviews),
        last_interview_status=interviews[0].status.value if interviews else None,  # type: ignore[arg-type]
    )


def interview_out(
    interview: Interview, vacancy_title: str, link: str | None = None
) -> InterviewOut:
    return InterviewOut(
        id=str(interview.id),
        status=interview.status.value,  # type: ignore[arg-type]
        vacancy_id=str(interview.vacancy_id),
        vacancy_title=vacancy_title,
        candidate_id=str(interview.candidate_id),
        candidate_name=interview.candidate.full_name,
        candidate_email=interview.candidate.email,
        invited_at=aware(interview.invited_at),  # type: ignore[arg-type]
        expires_at=aware(interview.expires_at),  # type: ignore[arg-type]
        opened_at=aware(interview.opened_at),
        consented_at=aware(interview.consented_at),
        started_at=aware(interview.started_at),
        completed_at=aware(interview.completed_at),
        evaluated_at=aware(interview.evaluated_at),
        decided_at=aware(interview.decided_at),
        decision=interview.decision,
        current_question_index=interview.current_question_index,
        question_count=len(interview.question_snapshot) if interview.question_snapshot else None,
        link=link,
    )


# ------------------------------------------------------------------ candidates


@candidates_router.get("", response_model=list[CandidateOut])
async def list_candidates(
    actor: CurrentActor,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> list[CandidateOut]:
    candidates = await CandidateService(session).list(actor, search=search)
    return [candidate_out(candidate) for candidate in candidates]


@candidates_router.post("", response_model=CandidateOut, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    payload: CandidateCreate, actor: CurrentActor, session: DbSession
) -> CandidateOut:
    return candidate_out(await CandidateService(session).create(actor, payload))


@candidates_router.post("/bulk", response_model=BulkCreateResult)
async def bulk_create_candidates(
    payload: CandidateBulkCreate, actor: CurrentActor, session: DbSession
) -> BulkCreateResult:
    service = CandidateService(session)
    created, existing, skipped = await service.bulk_create(actor, payload)
    invited = 0
    if payload.vacancy_id:
        interviews = InterviewService(session)
        for candidate in created + existing:
            try:
                await interviews.invite(
                    actor,
                    InviteRequest(vacancy_id=payload.vacancy_id, candidate_id=candidate.id),
                )
                invited += 1
            except HTTPException:
                raise
            except Exception:
                # Уже есть активное интервью — пропускаем, остальных приглашаем.
                await session.rollback()
    # Перечитываем, чтобы у карточек были актуальные интервью.
    fresh = {c.id: await service.get(actor, c.id) for c in created + existing}
    return BulkCreateResult(
        created=[candidate_out(fresh[c.id]) for c in created],
        existing=[candidate_out(fresh[c.id]) for c in existing],
        skipped_lines=skipped,
        invited=invited,
    )


@candidates_router.get("/{candidate_id}", response_model=CandidateOut)
async def get_candidate(
    candidate_id: UUID, actor: CurrentActor, session: DbSession
) -> CandidateOut:
    return candidate_out(await CandidateService(session).get(actor, candidate_id))


@candidates_router.patch("/{candidate_id}", response_model=CandidateOut)
async def update_candidate(
    candidate_id: UUID, payload: CandidateUpdate, actor: CurrentActor, session: DbSession
) -> CandidateOut:
    return candidate_out(await CandidateService(session).update(actor, candidate_id, payload))


@candidates_router.get("/{candidate_id}/interviews", response_model=list[InterviewOut])
async def candidate_interviews(
    candidate_id: UUID, actor: CurrentActor, session: DbSession
) -> list[InterviewOut]:
    interviews = await InterviewService(session).list(actor, candidate_id=candidate_id)
    titles = await vacancy_titles(session, interviews)
    return [interview_out(i, titles.get(i.vacancy_id, "")) for i in interviews]


# ------------------------------------------------------------------ interviews


@interviews_router.get("", response_model=list[InterviewOut])
async def list_interviews(
    actor: CurrentActor,
    session: DbSession,
    vacancy_id: UUID | None = None,
) -> list[InterviewOut]:
    interviews = await InterviewService(session).list(actor, vacancy_id=vacancy_id)
    titles = await vacancy_titles(session, interviews)
    return [interview_out(i, titles.get(i.vacancy_id, "")) for i in interviews]


@interviews_router.post("", response_model=InterviewOut, status_code=status.HTTP_201_CREATED)
async def invite(payload: InviteRequest, actor: CurrentActor, session: DbSession) -> InterviewOut:
    interview, token = await InterviewService(session).invite(actor, payload)
    titles = await vacancy_titles(session, [interview])
    return interview_out(interview, titles.get(interview.vacancy_id, ""), interview_link(token))


@interviews_router.get("/{interview_id}", response_model=InterviewOut)
async def get_interview(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> InterviewOut:
    interview = await InterviewService(session).get(actor, interview_id)
    titles = await vacancy_titles(session, [interview])
    return interview_out(interview, titles.get(interview.vacancy_id, ""))


@interviews_router.post("/{interview_id}/resend", response_model=InterviewOut)
async def resend_invitation(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> InterviewOut:
    interview, token = await InterviewService(session).resend(actor, interview_id)
    titles = await vacancy_titles(session, [interview])
    return interview_out(interview, titles.get(interview.vacancy_id, ""), interview_link(token))


@interviews_router.post("/{interview_id}/cancel", response_model=InterviewOut)
async def cancel_interview(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> InterviewOut:
    interview = await InterviewService(session).cancel(actor, interview_id)
    titles = await vacancy_titles(session, [interview])
    return interview_out(interview, titles.get(interview.vacancy_id, ""))


# ---------------------------------------------------------------------- public


def _public_out(
    interview: Interview, vacancy: Vacancy, organization: Organization
) -> InvitationPublicOut:
    return InvitationPublicOut(
        status=interview.status.value,  # type: ignore[arg-type]
        organization_name=organization.name,
        vacancy_title=vacancy.title,
        intro_text=vacancy.intro_text,
        question_count=len(interview.question_snapshot or vacancy.questions),
        estimated_minutes=estimated_minutes(vacancy),
        prep_seconds=vacancy.prep_seconds,
        max_answer_seconds=vacancy.max_answer_seconds,
        retakes_allowed=vacancy.retakes_allowed,
        practice_question_enabled=vacancy.practice_question_enabled,
        interview_mode=vacancy.interview_mode,
        expires_at=aware(interview.expires_at),  # type: ignore[arg-type]
        needs_consent=interview.status in (InterviewStatus.invited, InterviewStatus.opened),
        candidate_full_name=interview.consent_full_name or interview.candidate.full_name,
        candidate_email=interview.consent_email or interview.candidate.email,
        consent_documents=[
            ConsentDocumentOut(
                slug=doc.slug,
                title=doc.title,
                version=doc.version,
                hash=doc.hash,
                required=doc.required,
                checkbox_label=doc.checkbox_label,
            )
            for doc in consent_documents()
        ],
        current_question_index=interview.current_question_index,
    )


@public_router.get("/{token}", response_model=InvitationPublicOut)
async def public_invitation(
    token: str, session: DbSession, request: Request
) -> InvitationPublicOut:
    decision = public_rate_limiter.check(_client_ip(request))
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="Слишком много запросов, попробуйте позже")
    interview, vacancy, organization = await InterviewService(session).open(token)
    return _public_out(interview, vacancy, organization)


@public_router.post("/{token}/consent", response_model=InvitationPublicOut)
async def public_consent(
    token: str, payload: ConsentSubmit, session: DbSession, request: Request
) -> InvitationPublicOut:
    decision = public_rate_limiter.check(_client_ip(request))
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="Слишком много запросов, попробуйте позже")
    interview, vacancy, organization = await InterviewService(session).submit_consent(
        token, payload, ip=_client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _public_out(interview, vacancy, organization)
