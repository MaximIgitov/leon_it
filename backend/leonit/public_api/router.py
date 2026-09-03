"""Публичный API v1: ручки для интеграций (ATS, HR-боты, скрипты).

Каждая ручка требует область токена (``require_scope``); внутри сервисы ещё раз
проверяют действия через ``authorize`` — так у интеграции тот же периметр, что и
у сотрудника с теми же правами.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from leonit.api_tokens.deps import ApiActor, require_scope
from leonit.candidates.schemas import CandidateCreate
from leonit.core.deps import DbSession
from leonit.public_api.schemas import (
    ApiCandidate,
    ApiInterview,
    ApiInterviewReport,
    ApiInviteRequest,
    ApiRankingRow,
    ApiVacancy,
    ApiVacancyDetail,
)
from leonit.public_api.service import PublicApiService
from leonit.vacancies.models import VacancyStatus
from leonit.vacancies.schemas import VacancyCreate

TAG_VACANCIES = "Вакансии"
TAG_CANDIDATES = "Кандидаты"
TAG_INTERVIEWS = "Интервью"
TAG_REPORTS = "Отчёты"

router = APIRouter(prefix="/v1")

VacanciesRead = Annotated[ApiActor, Depends(require_scope("vacancies:read"))]
VacanciesWrite = Annotated[ApiActor, Depends(require_scope("vacancies:write"))]
CandidatesRead = Annotated[ApiActor, Depends(require_scope("candidates:read"))]
CandidatesWrite = Annotated[ApiActor, Depends(require_scope("candidates:write"))]
InterviewsRead = Annotated[ApiActor, Depends(require_scope("interviews:read"))]
ReportsRead = Annotated[ApiActor, Depends(require_scope("reports:read"))]

_ERRORS = {
    401: {"description": "Токен отсутствует, не найден, отозван или просрочен."},
    403: {"description": "У токена нет нужной области."},
    429: {"description": "Превышен лимит запросов на токен; см. заголовок Retry-After."},
}


# ------------------------------------------------------------------ vacancies


@router.get(
    "/vacancies",
    response_model=list[ApiVacancy],
    tags=[TAG_VACANCIES],
    summary="Список вакансий",
    description=(
        "Вакансии организации, новые сверху. Фильтр `status` — `draft`, `published` или "
        "`archived`. Кандидатов можно приглашать только по опубликованным вакансиям.\n\n"
        "Область: `vacancies:read`."
    ),
    responses=_ERRORS,
)
async def list_vacancies(
    actor: VacanciesRead,
    session: DbSession,
    status_filter: Annotated[VacancyStatus | None, Query(alias="status")] = None,
) -> list[ApiVacancy]:
    return await PublicApiService(session).list_vacancies(actor, status_filter)


@router.post(
    "/vacancies",
    response_model=ApiVacancyDetail,
    status_code=status.HTTP_201_CREATED,
    tags=[TAG_VACANCIES],
    summary="Создать черновик вакансии",
    description=(
        "Создаёт вакансию в статусе `draft`. Вопросы, рубрику и настройки интервью "
        "рекрутер дополняет в кабинете, там же публикует. Публикация через API намеренно "
        "не поддерживается: вакансия без вопросов не пройдёт проверку.\n\n"
        "Область: `vacancies:write`."
    ),
    responses=_ERRORS,
)
async def create_vacancy(
    payload: VacancyCreate, actor: VacanciesWrite, session: DbSession
) -> ApiVacancyDetail:
    return await PublicApiService(session).create_vacancy(actor, payload)


@router.get(
    "/vacancies/{vacancy_id}",
    response_model=ApiVacancyDetail,
    tags=[TAG_VACANCIES],
    summary="Карточка вакансии",
    description=(
        "Описание, требования, рубрика компетенций, настройки интервью и вопросы.\n\n"
        "Область: `vacancies:read`."
    ),
    responses={**_ERRORS, 404: {"description": "Вакансия не найдена в этой организации."}},
)
async def get_vacancy(
    vacancy_id: UUID, actor: VacanciesRead, session: DbSession
) -> ApiVacancyDetail:
    return await PublicApiService(session).get_vacancy(actor, vacancy_id)


@router.get(
    "/vacancies/{vacancy_id}/ranking",
    response_model=list[ApiRankingRow],
    tags=[TAG_REPORTS],
    summary="Ранжирование кандидатов по вакансии",
    description=(
        "Интервью по вакансии (кроме отменённых и истёкших) в том же порядке, что в "
        "кабинете: сначала те, кому модель поставила `needs_check` (их нужно посмотреть "
        "человеку), затем по убыванию `fit_score`, ещё не оценённые — в конце. "
        "`fit_score` и `recommendation` заполнены только у готового заключения; решение "
        "человека (`decision`) на порядок не влияет.\n\n"
        "Область: `reports:read`."
    ),
    responses={**_ERRORS, 404: {"description": "Вакансия не найдена в этой организации."}},
)
async def vacancy_ranking(
    vacancy_id: UUID, actor: ReportsRead, session: DbSession
) -> list[ApiRankingRow]:
    return await PublicApiService(session).ranking(actor, vacancy_id)


# ----------------------------------------------------------------- candidates


@router.get(
    "/candidates",
    response_model=list[ApiCandidate],
    tags=[TAG_CANDIDATES],
    summary="Список кандидатов",
    description=(
        "Кандидаты организации, новые сверху. `search` ищет по имени и e-mail без учёта "
        "регистра.\n\nОбласть: `candidates:read`."
    ),
    responses=_ERRORS,
)
async def list_candidates(
    actor: CandidatesRead,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> list[ApiCandidate]:
    return await PublicApiService(session).list_candidates(actor, search)


@router.post(
    "/candidates",
    response_model=ApiCandidate,
    status_code=status.HTTP_201_CREATED,
    tags=[TAG_CANDIDATES],
    summary="Создать кандидата",
    description=(
        "Кандидат уникален по e-mail внутри организации: повторное создание вернёт `409`. "
        "`external_ref` — ваш идентификатор, по нему удобно сопоставлять записи с ATS. "
        "Источник такого кандидата — `api`.\n\nОбласть: `candidates:write`."
    ),
    responses={**_ERRORS, 409: {"description": "Кандидат с таким e-mail уже есть."}},
)
async def create_candidate(
    payload: CandidateCreate, actor: CandidatesWrite, session: DbSession
) -> ApiCandidate:
    return await PublicApiService(session).create_candidate(actor, payload)


# ----------------------------------------------------------------- interviews


@router.post(
    "/interviews",
    response_model=ApiInterview,
    status_code=status.HTTP_201_CREATED,
    tags=[TAG_INTERVIEWS],
    summary="Пригласить кандидата на интервью",
    description=(
        "Создаёт интервью по опубликованной вакансии. Кандидат находится по e-mail или "
        "создаётся. В ответе поле `link` — ссылка для кандидата; она **показывается один "
        "раз**, дальше хранится только хеш. При `send_email=true` письмо с той же ссылкой "
        "уходит кандидату.\n\n"
        "У кандидата не может быть двух активных интервью по одной вакансии — `409`.\n\n"
        "Область: `candidates:write`."
    ),
    responses={
        **_ERRORS,
        404: {"description": "Вакансия не найдена."},
        409: {"description": "Активное интервью по этой вакансии уже есть."},
        422: {"description": "Вакансия не опубликована или данные неполные."},
    },
)
async def invite(
    payload: ApiInviteRequest, actor: CandidatesWrite, session: DbSession
) -> ApiInterview:
    return await PublicApiService(session).invite(actor, payload)


@router.get(
    "/interviews",
    response_model=list[ApiInterview],
    tags=[TAG_INTERVIEWS],
    summary="Список интервью",
    description=(
        "Интервью организации, новые сверху; фильтры `vacancy_id` и `candidate_id`. "
        "`fit_score` и `recommendation` заполняются после оценки модели.\n\n"
        "Область: `interviews:read`."
    ),
    responses=_ERRORS,
)
async def list_interviews(
    actor: InterviewsRead,
    session: DbSession,
    vacancy_id: UUID | None = None,
    candidate_id: UUID | None = None,
) -> list[ApiInterview]:
    return await PublicApiService(session).list_interviews(
        actor, vacancy_id=vacancy_id, candidate_id=candidate_id
    )


@router.get(
    "/interviews/{interview_id}",
    response_model=ApiInterview,
    tags=[TAG_INTERVIEWS],
    summary="Статус интервью",
    description=(
        "Статус, таймстемпы переходов, решение человека и, если есть заключение модели, "
        "`fit_score` с `recommendation`. Для опроса статуса достаточно этой ручки — отчёт "
        "тяжелее.\n\nОбласть: `interviews:read`."
    ),
    responses={**_ERRORS, 404: {"description": "Интервью не найдено."}},
)
async def get_interview(
    interview_id: UUID, actor: InterviewsRead, session: DbSession
) -> ApiInterview:
    return await PublicApiService(session).get_interview(actor, interview_id)


@router.get(
    "/interviews/{interview_id}/report",
    response_model=ApiInterviewReport,
    tags=[TAG_REPORTS],
    summary="Отчёт по интервью",
    description=(
        "Заключение модели, ответы с транскриптами и таймкодами, решение человека. "
        "Ссылки на видео (`media_url`) выдаются только токенам с областью `media:read` и "
        "живут 15 минут — запрашивайте отчёт заново, а не храните ссылки.\n\n"
        "Область: `reports:read` (+ `media:read` для ссылок)."
    ),
    responses={**_ERRORS, 404: {"description": "Интервью не найдено."}},
)
async def interview_report(
    interview_id: UUID, actor: ReportsRead, session: DbSession
) -> ApiInterviewReport:
    return await PublicApiService(session).report(
        actor, interview_id, with_media="media:read" in actor.scopes
    )
