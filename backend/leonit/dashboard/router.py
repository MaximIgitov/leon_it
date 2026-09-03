from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from leonit.accounts.deps import CurrentActor
from leonit.core.deps import DbSession
from leonit.dashboard.schemas import DashboardOverview, DashboardTimeseries
from leonit.dashboard.service import DashboardService, resolve_period

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Период: ``from``/``to`` — ISO-даты (без зоны — UTC); без параметров —
# последние 30 дней; ``all_time=true`` снимает нижнюю границу.
PeriodFrom = Annotated[datetime | None, Query(alias="from")]
PeriodTo = Annotated[datetime | None, Query(alias="to")]
AllTime = Annotated[bool, Query()]


@router.get("/overview", response_model=DashboardOverview)
async def overview(
    actor: CurrentActor,
    session: DbSession,
    from_: PeriodFrom = None,
    to: PeriodTo = None,
    all_time: AllTime = False,
) -> DashboardOverview:
    period = resolve_period(from_, to, all_time=all_time)
    return await DashboardService(session).overview(actor, period=period)


@router.get("/vacancies/{vacancy_id}", response_model=DashboardOverview)
async def vacancy_overview(
    vacancy_id: UUID,
    actor: CurrentActor,
    session: DbSession,
    from_: PeriodFrom = None,
    to: PeriodTo = None,
    all_time: AllTime = False,
) -> DashboardOverview:
    period = resolve_period(from_, to, all_time=all_time)
    return await DashboardService(session).overview(actor, period=period, vacancy_id=vacancy_id)


@router.get("/timeseries", response_model=DashboardTimeseries)
async def timeseries(
    actor: CurrentActor,
    session: DbSession,
    vacancy_id: UUID | None = None,
    from_: PeriodFrom = None,
    to: PeriodTo = None,
    all_time: AllTime = False,
    # Смещение зоны пользователя в минутах (как -Date.getTimezoneOffset()).
    tz_offset_minutes: Annotated[int, Query(ge=-14 * 60, le=14 * 60)] = 0,
) -> DashboardTimeseries:
    period = resolve_period(from_, to, all_time=all_time)
    return await DashboardService(session).timeseries(
        actor, period=period, vacancy_id=vacancy_id, tz_offset_minutes=tz_offset_minutes
    )
