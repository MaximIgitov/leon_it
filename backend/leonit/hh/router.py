from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import RedirectResponse

from leonit.accounts.deps import CurrentActor
from leonit.core.deps import DbSession, SettingsDep
from leonit.core.errors import DomainError
from leonit.core.logging import get_logger
from leonit.hh.schemas import (
    DialogOut,
    DialogSettings,
    HhStatusOut,
    HhTokenConnectIn,
    HhVacancyOut,
    LinkVacancyIn,
    NegotiationOut,
    OAuthStartOut,
    SyncQueuedOut,
    TakeOverIn,
    VacancyLinkOut,
)
from leonit.hh.service import HhService

router = APIRouter(prefix="/integrations/hh", tags=["integrations:hh"])
log = get_logger(__name__)


@router.get("/status", response_model=HhStatusOut)
async def hh_status(actor: CurrentActor, session: DbSession) -> HhStatusOut:
    return await HhService(session).status(actor)


@router.post("/oauth/start", response_model=OAuthStartOut)
async def oauth_start(actor: CurrentActor, session: DbSession) -> OAuthStartOut:
    return OAuthStartOut(url=await HhService(session).oauth_start(actor))


@router.get("/callback", include_in_schema=False)
async def oauth_callback(
    session: DbSession,
    settings: SettingsDep,
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Возврат из HH: обмен кода и редирект на страницу интеграции."""
    target = f"{settings.PUBLIC_URL}/integrations/hh"
    if error or not code or not state:
        return RedirectResponse(f"{target}?status=error&reason=denied", status_code=302)
    try:
        await HhService(session).oauth_callback(code=code, state=state)
    except DomainError as failure:
        log.warning("hh oauth callback rejected: %s", failure.detail)
        reason = "state" if failure.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT else "hh"
        return RedirectResponse(f"{target}?status=error&reason={reason}", status_code=302)
    except Exception:
        log.exception("hh oauth callback failed")
        return RedirectResponse(f"{target}?status=error&reason=unexpected", status_code=302)
    return RedirectResponse(f"{target}?status=connected", status_code=302)


@router.post("/connect-demo", response_model=HhStatusOut)
async def connect_demo(actor: CurrentActor, session: DbSession) -> HhStatusOut:
    service = HhService(session)
    await service.connect_demo(actor)
    return await service.status(actor)


@router.post("/connect-token", response_model=HhStatusOut)
async def connect_token(
    payload: HhTokenConnectIn, actor: CurrentActor, session: DbSession
) -> HhStatusOut:
    """Подключение готовым токеном (без OAuth): токен не логируется и хранится шифрованным."""
    service = HhService(session)
    await service.connect_with_token(
        actor,
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
        expires_at=payload.expires_at,
    )
    return await service.status(actor)


@router.post("/disconnect", response_model=HhStatusOut)
async def disconnect(actor: CurrentActor, session: DbSession) -> HhStatusOut:
    service = HhService(session)
    await service.disconnect(actor)
    return await service.status(actor)


@router.get("/vacancies", response_model=list[HhVacancyOut])
async def list_hh_vacancies(actor: CurrentActor, session: DbSession) -> list[HhVacancyOut]:
    return await HhService(session).list_hh_vacancies(actor)


@router.post(
    "/vacancies/{hh_vacancy_id}/import",
    response_model=VacancyLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_vacancy(
    hh_vacancy_id: str, actor: CurrentActor, session: DbSession
) -> VacancyLinkOut:
    return await HhService(session).import_vacancy(actor, hh_vacancy_id)


@router.post("/vacancies/{hh_vacancy_id}/link", response_model=VacancyLinkOut)
async def link_vacancy(
    hh_vacancy_id: str, payload: LinkVacancyIn, actor: CurrentActor, session: DbSession
) -> VacancyLinkOut:
    return await HhService(session).link_vacancy(actor, hh_vacancy_id, UUID(payload.vacancy_id))


@router.get("/links", response_model=list[VacancyLinkOut])
async def list_links(actor: CurrentActor, session: DbSession) -> list[VacancyLinkOut]:
    return await HhService(session).list_links(actor)


@router.get("/links/{link_id}/dialog", response_model=DialogOut)
async def get_dialog(link_id: UUID, actor: CurrentActor, session: DbSession) -> DialogOut:
    return await HhService(session).get_dialog(actor, link_id)


@router.put("/links/{link_id}/dialog", response_model=DialogOut)
async def update_dialog(
    link_id: UUID, payload: DialogSettings, actor: CurrentActor, session: DbSession
) -> DialogOut:
    return await HhService(session).update_dialog(actor, link_id, payload)


@router.get("/negotiations", response_model=list[NegotiationOut])
async def list_negotiations(
    actor: CurrentActor,
    session: DbSession,
    candidate_id: Annotated[UUID | None, Query()] = None,
    link_id: Annotated[UUID | None, Query()] = None,
) -> list[NegotiationOut]:
    return await HhService(session).list_negotiations(
        actor, candidate_id=candidate_id, link_id=link_id
    )


@router.post("/negotiations/{negotiation_id}/take-over", response_model=NegotiationOut)
async def take_over(
    negotiation_id: UUID, payload: TakeOverIn, actor: CurrentActor, session: DbSession
) -> NegotiationOut:
    return await HhService(session).take_over(actor, negotiation_id, payload)


@router.post("/sync", response_model=SyncQueuedOut, status_code=status.HTTP_202_ACCEPTED)
async def sync_now(actor: CurrentActor, session: DbSession) -> SyncQueuedOut:
    job = await HhService(session).request_sync(actor)
    return SyncQueuedOut(job_id=str(job.id), queued=True)


@router.post(
    "/webhook/{secret}",
    response_model=SyncQueuedOut,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
async def webhook(secret: str, session: DbSession) -> SyncQueuedOut:
    """Уведомление HH — только триггер перечитывания; тело не разбирается."""
    job = await HhService(session).handle_webhook(secret)
    return SyncQueuedOut(job_id=str(job.id), queued=True)
