from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import text

from leonit.core.deps import DbSession, SettingsDep
from leonit.core.observability import metrics

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Жив ли процесс. Не трогает базу: балансировщик спрашивает часто."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: DbSession) -> dict[str, str]:
    """Готов ли сервис принимать трафик: база отвечает."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception as error:  # любая ошибка базы означает «не готов»
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
        ) from error
    return {"status": "ready"}


@router.get("/metrics")
async def metrics_snapshot(
    settings: SettingsDep,
    x_metrics_token: str | None = Header(default=None),
) -> dict:
    """Счётчики и латентности процесса. На проде — только по токену."""
    if settings.METRICS_TOKEN:
        if x_metrics_token != settings.METRICS_TOKEN:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    elif settings.is_production:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return metrics.snapshot()
