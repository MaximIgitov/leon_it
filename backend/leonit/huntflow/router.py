from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from leonit.accounts.deps import CurrentActor
from leonit.accounts.models import User
from leonit.core.authz import Actor, can
from leonit.core.deps import DbSession, SettingsDep
from leonit.core.time import aware
from leonit.huntflow.client import HuntflowAccount, HuntflowStatus, HuntflowVacancy
from leonit.huntflow.models import HuntflowApplicant, HuntflowConnection, HuntflowVacancyLink
from leonit.huntflow.schemas import (
    ConnectIn,
    ConnectionOut,
    HuntflowAccountOut,
    HuntflowStatusOut,
    HuntflowVacanciesOut,
    HuntflowVacancyOut,
    ImportResult,
    JobBrief,
    LinkIn,
    PushIn,
    PushStatusOut,
    SelectAccountIn,
    VacancyLinkOut,
)
from leonit.huntflow.service import HuntflowService, demo_available
from leonit.jobs.models import Job
from leonit.vacancies.models import Vacancy

router = APIRouter(prefix="/integrations/huntflow", tags=["integrations"])


def _account_out(account: HuntflowAccount) -> HuntflowAccountOut:
    return HuntflowAccountOut(id=account.id, name=account.name, nick=account.nick)


async def _connection_out(
    session,
    actor: Actor,
    settings,
    connection: HuntflowConnection | None,
    *,
    accounts: list[HuntflowAccount] = (),  # type: ignore[assignment]
    linked: int = 0,
) -> ConnectionOut:
    demo = demo_available(settings)
    manage = can(actor, "integrations.manage")
    if connection is None:
        return ConnectionOut(connected=False, demo_available=demo, can_manage=manage)
    connected_by = (
        await session.get(User, connection.connected_by_user_id)
        if connection.connected_by_user_id
        else None
    )
    account = (
        HuntflowAccountOut(id=connection.account_id, name=connection.account_name or "")
        if connection.account_id is not None
        else None
    )
    return ConnectionOut(
        connected=True,
        mode=connection.mode.value,  # type: ignore[arg-type]
        status=connection.status.value,  # type: ignore[arg-type]
        account=account,
        owner_name=connection.owner_name,
        owner_email=connection.owner_email,
        last_error=connection.last_error,
        last_checked_at=aware(connection.last_checked_at),
        connected_at=aware(connection.created_at),
        connected_by_email=connected_by.email if connected_by else None,
        available_accounts=[_account_out(a) for a in accounts],
        linked_vacancies=linked,
        demo_available=demo,
        can_manage=manage,
    )


def link_out(link: HuntflowVacancyLink, vacancy: Vacancy) -> VacancyLinkOut:
    return VacancyLinkOut(
        vacancy_id=str(vacancy.id),
        vacancy_title=vacancy.title,
        vacancy_status=vacancy.status.value,
        huntflow_vacancy_id=link.huntflow_vacancy_id,
        huntflow_vacancy_title=link.huntflow_vacancy_title,
        status_id=link.status_id,
        status_name=link.status_name,
        last_imported_at=aware(link.last_imported_at),
        created_at=aware(link.created_at),  # type: ignore[arg-type]
    )


def _status_out(item: HuntflowStatus) -> HuntflowStatusOut:
    return HuntflowStatusOut(id=item.id, name=item.name, type=item.type, order=item.order)


def _vacancy_out(item: HuntflowVacancy, links: list[VacancyLinkOut]) -> HuntflowVacancyOut:
    return HuntflowVacancyOut(
        id=item.id, position=item.position, state=item.state, company=item.company, links=links
    )


def push_out(candidate_id: UUID, row: HuntflowApplicant | None, job: Job | None) -> PushStatusOut:
    if row is None:
        return PushStatusOut(candidate_id=str(candidate_id), status="not_pushed")
    return PushStatusOut(
        candidate_id=str(candidate_id),
        status=row.status.value,  # type: ignore[arg-type]
        interview_id=str(row.interview_id) if row.interview_id else None,
        huntflow_applicant_id=row.huntflow_applicant_id,
        huntflow_vacancy_id=row.huntflow_vacancy_id,
        huntflow_status_id=row.huntflow_status_id,
        last_pushed_at=aware(row.last_pushed_at),
        last_error=row.last_error,
        report_share_url=row.report_share_url,
        job=JobBrief(
            id=str(job.id),
            status=job.status.value,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            run_after=aware(job.run_after),
            last_error=job.last_error,
        )
        if job is not None
        else None,
    )


# ------------------------------------------------------------------ подключение


@router.get("", response_model=ConnectionOut)
async def get_status(
    actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> ConnectionOut:
    connection, accounts, linked = await HuntflowService(session, settings).status(actor)
    return await _connection_out(
        session, actor, settings, connection, accounts=accounts, linked=linked
    )


@router.post("/connect", response_model=ConnectionOut)
async def connect(
    payload: ConnectIn, actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> ConnectionOut:
    service = HuntflowService(session, settings)
    await service.connect(actor, payload)
    connection, accounts, linked = await service.status(actor)
    return await _connection_out(
        session, actor, settings, connection, accounts=accounts, linked=linked
    )


@router.post("/account", response_model=ConnectionOut)
async def select_account(
    payload: SelectAccountIn, actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> ConnectionOut:
    service = HuntflowService(session, settings)
    await service.select_account(actor, payload.account_id)
    connection, accounts, linked = await service.status(actor)
    return await _connection_out(
        session, actor, settings, connection, accounts=accounts, linked=linked
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(actor: CurrentActor, session: DbSession, settings: SettingsDep) -> None:
    await HuntflowService(session, settings).disconnect(actor)


# --------------------------------------------------------------------- вакансии


@router.get("/vacancies", response_model=HuntflowVacanciesOut)
async def list_vacancies(
    actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> HuntflowVacanciesOut:
    vacancies, statuses, links = await HuntflowService(session, settings).list_vacancies(actor)
    by_remote: dict[int, list[VacancyLinkOut]] = {}
    for link, vacancy in links:
        by_remote.setdefault(link.huntflow_vacancy_id, []).append(link_out(link, vacancy))
    return HuntflowVacanciesOut(
        items=[_vacancy_out(v, by_remote.get(v.id, [])) for v in vacancies],
        statuses=[_status_out(s) for s in statuses],
    )


@router.get("/links", response_model=list[VacancyLinkOut])
async def list_links(
    actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> list[VacancyLinkOut]:
    return [link_out(link, v) for link, v in await HuntflowService(session, settings).links(actor)]


@router.put("/links/{vacancy_id}", response_model=VacancyLinkOut)
async def link_vacancy(
    vacancy_id: UUID,
    payload: LinkIn,
    actor: CurrentActor,
    session: DbSession,
    settings: SettingsDep,
) -> VacancyLinkOut:
    link, vacancy = await HuntflowService(session, settings).link_vacancy(
        actor, vacancy_id, payload
    )
    return link_out(link, vacancy)


@router.delete("/links/{vacancy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_vacancy(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> None:
    await HuntflowService(session, settings).unlink_vacancy(actor, vacancy_id)


@router.post("/links/{vacancy_id}/import", response_model=ImportResult)
async def import_applicants(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> ImportResult:
    stats = await HuntflowService(session, settings).import_applicants(actor, vacancy_id)
    return ImportResult(**stats)


# --------------------------------------------------------------------- передача


@router.post(
    "/candidates/{candidate_id}/push",
    response_model=PushStatusOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def push_candidate(
    candidate_id: UUID,
    payload: PushIn,
    actor: CurrentActor,
    session: DbSession,
    settings: SettingsDep,
) -> PushStatusOut:
    row, job = await HuntflowService(session, settings).push_candidate(actor, candidate_id, payload)
    return push_out(candidate_id, row, job)


@router.get("/candidates/{candidate_id}/push", response_model=PushStatusOut)
async def push_status(
    candidate_id: UUID, actor: CurrentActor, session: DbSession, settings: SettingsDep
) -> PushStatusOut:
    candidate, row, job = await HuntflowService(session, settings).push_status(actor, candidate_id)
    return push_out(candidate.id, row, job)
