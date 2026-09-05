"""Задача ``avatar.prewarm``: клипы вопросов вакансии готовятся заранее.

Рендер у провайдера занимает минуты, а кандидат ждать не должен: клипы
рендерятся при публикации вакансии и при смене вопросов или голоса, комната
берёт их из кэша. Промах в комнате тоже ставит эту задачу, чтобы следующий
кандидат клип получил. Уточняющие вопросы генерируются на лету, их аватар не
озвучивает.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.avatar.cache import get_or_render, lookup
from leonit.avatar.registry import get_avatar_provider
from leonit.core.config import get_settings
from leonit.core.logging import get_logger
from leonit.core.storage import get_storage
from leonit.jobs import service as jobs
from leonit.jobs.registry import JobContext, job
from leonit.vacancies.models import Vacancy

log = get_logger(__name__)

PREWARM_KIND = "avatar.prewarm"


def prewarm_dedupe_key(vacancy_id: UUID) -> str:
    return f"{PREWARM_KIND}:{vacancy_id}"


async def schedule_prewarm(session: AsyncSession, vacancy_id: UUID) -> None:
    """Поставить прогрев без дублей; коммитит вызывающий вместе со своими изменениями."""
    await jobs.enqueue(
        session,
        PREWARM_KIND,
        {"vacancy_id": str(vacancy_id)},
        dedupe_key=prewarm_dedupe_key(vacancy_id),
        max_attempts=3,
    )


@job(PREWARM_KIND, resource="default")
async def prewarm(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    settings = get_settings()
    if not settings.AVATAR_ENABLED:
        return {"skipped": "avatar_disabled"}
    provider = get_avatar_provider(settings)
    if not provider.enabled:
        return {"skipped": "provider_disabled"}
    vacancy_id = UUID(str(payload["vacancy_id"]))
    async with ctx.session_maker() as session:
        vacancy = await session.get(Vacancy, vacancy_id, options=[selectinload(Vacancy.questions)])
        if vacancy is None:
            return {"skipped": "vacancy_missing"}
        if not vacancy.avatar_enabled:
            return {"skipped": "avatar_off"}
        texts = [question.text for question in vacancy.questions]
        voice, language = vacancy.voice, vacancy.language
    storage = get_storage()
    rendered = cached = failed = 0
    for text in texts:
        if await lookup(storage, provider, text, voice, language) is not None:
            cached += 1
            continue
        try:
            clip = await get_or_render(storage, provider, text, voice, language)
        except Exception as error:  # один провальный клип не отменяет остальные
            failed += 1
            log.warning("avatar.prewarm.failed vacancy=%s error=%s", vacancy_id, error)
            continue
        if clip is None:
            failed += 1
        else:
            rendered += 1
        await ctx.heartbeat()
    result: dict[str, Any] = {"rendered": rendered, "cached": cached, "failed": failed}
    balance = getattr(provider, "balance_usd", None)
    if callable(balance):
        try:
            result["balance_usd"] = await balance()
        except Exception as error:
            log.warning("avatar.prewarm.balance_unavailable error=%s", error)
    log.info("avatar.prewarm vacancy=%s result=%s", vacancy_id, result)
    if failed and not rendered and not cached:
        # Ни одного клипа: скорее всего провайдер недоступен, пусть воркер повторит позже.
        raise RuntimeError(f"ни один клип не отрендерился (ошибок: {failed})")
    return result
