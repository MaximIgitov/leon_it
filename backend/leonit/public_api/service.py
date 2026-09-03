"""Публичный API поверх сервисов кабинета.

Здесь нет бизнес-логики: сервисы вакансий, кандидатов, отчётов и оценки получают
``ApiActor`` как обычного участника, а этот слой только переводит доменные
объекты и схемы кабинета в схемы v1. Ранжирование и баллы — те же, что видит
рекрутер: единственный источник — ``leonit.evaluation``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from leonit.candidates.models import Candidate, CandidateSource, Interview
from leonit.candidates.router import candidate_out, interview_out
from leonit.candidates.schemas import CandidateCreate, InviteRequest
from leonit.candidates.service import (
    CandidateService,
    InterviewService,
    interview_link,
    vacancy_titles,
)
from leonit.core.authz import Actor
from leonit.evaluation.service import ranking as evaluation_ranking
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


def api_candidate(candidate: Candidate) -> ApiCandidate:
    return ApiCandidate(**candidate_out(candidate).model_dump())


def _scores(evaluation: dict[str, Any] | None) -> tuple[float | None, str | None]:
    """Балл и рекомендация — только из готового заключения.

    Строка ``evaluations`` существует и в статусах ``pending`` / ``failed``
    (например, после «Переобработать»); интеграции результат показывается лишь
    когда он есть — как в ранжировании кабинета.
    """
    if not evaluation or evaluation.get("status") != "done":
        return None, None
    return evaluation.get("fit_score"), evaluation.get("recommendation")


def api_interview(
    interview: Interview,
    vacancy_title: str,
    evaluation: dict[str, Any] | None,
    *,
    link: str | None = None,
) -> ApiInterview:
    fit_score, recommendation = _scores(evaluation)
    # Та же карточка, что в кабинете, плюс итог оценки; поля, которых нет в v1
    # (например, current_question_index), схема отбрасывает.
    return ApiInterview(
        **interview_out(interview, vacancy_title, link).model_dump(),
        fit_score=fit_score,
        recommendation=recommendation,  # type: ignore[arg-type]
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

    async def _interviews(
        self, interviews: list[Interview], *, links: dict[UUID, str] | None = None
    ) -> list[ApiInterview]:
        titles = await vacancy_titles(self.session, interviews)
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
        """Тот же порядок, что в кабинете (`GET /vacancies/{id}/ranking`), плюс позиция."""
        rows = await evaluation_ranking(self.session, actor, vacancy_id)
        return [
            ApiRankingRow(position=index + 1, **row.model_dump()) for index, row in enumerate(rows)
        ]
