from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from leonit.accounts.deps import CurrentActor
from leonit.core.deps import DbSession
from leonit.vacancies.models import VacancyStatus
from leonit.vacancies.schemas import (
    QuestionsReplace,
    VacancyCreate,
    VacancyDetailOut,
    VacancyListItem,
    VacancyUpdate,
)
from leonit.vacancies.service import VacancyService, vacancy_detail_out, vacancy_list_item

router = APIRouter(prefix="/vacancies", tags=["vacancies"])


@router.get("", response_model=list[VacancyListItem])
async def list_vacancies(
    actor: CurrentActor,
    session: DbSession,
    status_filter: Annotated[VacancyStatus | None, Query(alias="status")] = None,
) -> list[VacancyListItem]:
    vacancies = await VacancyService(session).list(actor, status_filter)
    return [vacancy_list_item(vacancy) for vacancy in vacancies]


@router.post("", response_model=VacancyDetailOut, status_code=status.HTTP_201_CREATED)
async def create_vacancy(
    payload: VacancyCreate, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    return vacancy_detail_out(await VacancyService(session).create(actor, payload))


@router.get("/{vacancy_id}", response_model=VacancyDetailOut)
async def get_vacancy(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    return vacancy_detail_out(await VacancyService(session).get(actor, vacancy_id))


@router.patch("/{vacancy_id}", response_model=VacancyDetailOut)
async def update_vacancy(
    vacancy_id: UUID, payload: VacancyUpdate, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    return vacancy_detail_out(await VacancyService(session).update(actor, vacancy_id, payload))


@router.put("/{vacancy_id}/questions", response_model=VacancyDetailOut)
async def replace_questions(
    vacancy_id: UUID, payload: QuestionsReplace, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    vacancy = await VacancyService(session).replace_questions(actor, vacancy_id, payload.questions)
    return vacancy_detail_out(vacancy)


@router.post("/{vacancy_id}/publish", response_model=VacancyDetailOut)
async def publish_vacancy(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    return vacancy_detail_out(await VacancyService(session).publish(actor, vacancy_id))


@router.post("/{vacancy_id}/unpublish", response_model=VacancyDetailOut)
async def unpublish_vacancy(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    return vacancy_detail_out(await VacancyService(session).unpublish(actor, vacancy_id))


@router.post("/{vacancy_id}/archive", response_model=VacancyDetailOut)
async def archive_vacancy(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    return vacancy_detail_out(await VacancyService(session).archive(actor, vacancy_id))


@router.post("/{vacancy_id}/restore", response_model=VacancyDetailOut)
async def restore_vacancy(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession
) -> VacancyDetailOut:
    return vacancy_detail_out(await VacancyService(session).restore(actor, vacancy_id))
