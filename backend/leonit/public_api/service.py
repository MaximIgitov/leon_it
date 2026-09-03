"""Публичный API поверх сервисов кабинета.

Здесь нет бизнес-логики: сервисы вакансий, кандидатов и отчётов получают
``ApiActor`` как обычного участника, а этот слой только переводит доменные
объекты в схемы v1.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.candidates.models import CandidateSource, Interview
from leonit.candidates.router import candidate_out
from leonit.candidates.schemas import CandidateCreate, InviteRequest
from leonit.candidates.service import CandidateService, InterviewService, interview_link
from leonit.core.authz import Actor
from leonit.core.time import aware
from leonit.public_api.schemas import (
    ApiCandidate,
    ApiEvaluation,
    ApiInterview,
    ApiInterviewReport,
    ApiInviteRequest,
    ApiRankingRow,
    ApiReportAnswer,
    ApiVacancy,
    ApiVacancyDetail,
)
from leonit.reports.service import ReportService
from leonit.vacancies.models import Vacancy, VacancyStatus
from leonit.vacancies.schemas import VacancyCreate
from leonit.vacancies.service import VacancyService, vacancy_detail_out, vacancy_list_item


def api_vacancy(vacancy: Vacancy) -> ApiVacancy:
    return ApiVacancy(**vacancy_list_item(vacancy).model_dump())


def api_vacancy_detail(vacancy: Vacancy) -> ApiVacancyDetail:
    return ApiVacancyDetail(**vacancy_detail_out(vacancy).model_dump())


def api_candidate(candidate) -> ApiCandidate:
    return ApiCandidate(**candidate_out(candidate).model_dump())


def api_interview(
    interview: Interview,
    vacancy_title: str,
    evaluation: dict[str, Any] | None,
    *,
    link: str | None = None,
) -> ApiInterview:
    evaluation = evaluation or {}
    return ApiInterview(
        id=str(interview.id),
        status=interview.status.value,  # type: ignore[arg-type]
        vacancy_id=str(interview.vacancy_id),
        vacancy_title=vacancy_title,
        candidate_id=str(interview.candidate_id),
        candidate_name=interview.consent_full_name or interview.candidate.full_name,
        candidate_email=interview.candidate.email,
        invited_at=aware(interview.invited_at),  # type: ignore[arg-type]
        expires_at=aware(interview.expires_at),  # type: ignore[arg-type]
        opened_at=aware(interview.opened_at),
        consented_at=aware(interview.consented_at),
        started_at=aware(interview.started_at),
        completed_at=aware(interview.completed_at),
        evaluated_at=aware(interview.evaluated_at),
        decided_at=aware(interview.decided_at),
        decision=interview.decision,  # type: ignore[arg-type]
        question_count=len(interview.question_snapshot) if interview.question_snapshot else None,
        fit_score=evaluation.get("fit_score"),
        recommendation=evaluation.get("recommendation"),
        link=link,
    )


class PublicApiService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reports = ReportService(session)

    # -------------------------------------------------------------- vacancies

    async def list_vacancies(self, actor: Actor, status: VacancyStatus | None) -> list[ApiVacancy]:
        return [api_vacancy(v) for v in await VacancyService(self.session).list(actor, status)]

    async def get_vacancy(self, actor: Actor, vacancy_id: UUID) -> ApiVacancyDetail:
        return api_vacancy_detail(await VacancyService(self.session).get(actor, vacancy_id))

    async def create_vacancy(self, actor: Actor, payload: VacancyCreate) -> ApiVacancyDetail:
        return api_vacancy_detail(await VacancyService(self.session).create(actor, payload))

    # ------------------------------------------------------------- candidates

    async def list_candidates(self, actor: Actor, search: str | None) -> list[ApiCandidate]:
        candidates = await CandidateService(self.session).list(actor, search=search)
        return [api_candidate(c) for c in candidates]

    async def create_candidate(self, actor: Actor, payload: CandidateCreate) -> ApiCandidate:
        candidate = await CandidateService(self.session).create(
            actor, payload, source=CandidateSource.api
        )
        return api_candidate(candidate)

    # ------------------------------------------------------------- interviews

    async def _titles(self, interviews: list[Interview]) -> dict[UUID, str]:
        ids = {interview.vacancy_id for interview in interviews}
        if not ids:
            return {}
        rows = await self.session.execute(
            select(Vacancy.id, Vacancy.title).where(Vacancy.id.in_(ids))
        )
        return {vacancy_id: title for vacancy_id, title in rows.all()}

    async def _interviews(
        self, interviews: list[Interview], *, links: dict[UUID, str] | None = None
    ) -> list[ApiInterview]:
        titles = await self._titles(interviews)
        evaluations = await self.reports.evaluation_payloads([i.id for i in interviews])
        return [
            api_interview(
                i,
                titles.get(i.vacancy_id, ""),
                evaluations.get(i.id),
                link=(links or {}).get(i.id),
            )
            for i in interviews
        ]

    async def invite(self, actor: Actor, payload: ApiInviteRequest) -> ApiInterview:
        interview, token = await InterviewService(self.session).invite(
            actor,
            InviteRequest(
                vacancy_id=payload.vacancy_id,
                full_name=payload.full_name,
                email=payload.email,
                send_email=payload.send_email,
            ),
            source=CandidateSource.api,
        )
        items = await self._interviews([interview], links={interview.id: interview_link(token)})
        return items[0]

    async def list_interviews(
        self, actor: Actor, *, vacancy_id: UUID | None, candidate_id: UUID | None
    ) -> list[ApiInterview]:
        interviews = await InterviewService(self.session).list(
            actor, vacancy_id=vacancy_id, candidate_id=candidate_id
        )
        return await self._interviews(interviews)

    async def get_interview(self, actor: Actor, interview_id: UUID) -> ApiInterview:
        interview = await InterviewService(self.session).get(actor, interview_id)
        return (await self._interviews([interview]))[0]

    # ---------------------------------------------------------------- reports

    async def report(
        self, actor: Actor, interview_id: UUID, *, with_media: bool
    ) -> ApiInterviewReport:
        data = await self.reports.report(actor, interview_id, with_media=with_media)
        interview: Interview = data["interview"]
        evaluation = data["evaluation"]
        return ApiInterviewReport(
            interview=api_interview(interview, data["vacancy_title"], evaluation),
            decision_note=interview.decision_note,
            evaluation=ApiEvaluation(**evaluation) if evaluation else None,
            answers=[ApiReportAnswer(**row) for row in data["answers"]],
            media_urls_included=with_media,
        )

    async def ranking(self, actor: Actor, vacancy_id: UUID) -> list[ApiRankingRow]:
        rows = await self.reports.ranking(actor, vacancy_id)
        return [ApiRankingRow(position=index + 1, **row) for index, row in enumerate(rows)]
