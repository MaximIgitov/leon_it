"""Фабрика приложения.

Каждая предметная область регистрирует свой роутер в ``ROUTERS``; middleware
подключаются снаружи внутрь: CORS → security-заголовки → контекст запроса, чтобы
request-id и access-лог покрывали весь конвейер, включая ответы CORS.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from leonit.accounts.router import auth_router, invites_router, organization_router
from leonit.ai.gateway import shutdown_gateway
from leonit.api_tokens.router import router as api_tokens_router
from leonit.assistant.router import router as assistant_router
from leonit.candidates.router import candidates_router, interviews_router, public_router
from leonit.core.config import get_settings
from leonit.core.db import dispose_engine
from leonit.core.errors import install_error_handlers
from leonit.core.logging import setup_logging
from leonit.core.observability import RequestContextMiddleware
from leonit.core.security_headers import SecurityHeadersMiddleware
from leonit.evaluation.router import router as evaluation_router
from leonit.health.router import router as health_router
from leonit.interviews.router import room_router
from leonit.interviews.router import staff_router as interview_staff_router
from leonit.legal.router import router as legal_router
from leonit.media.router import router as media_router
from leonit.notifications.router import router as emails_router
from leonit.public_api.docs import API_DESCRIPTION, OPENAPI_TAGS
from leonit.public_api.docs import router as api_docs_router
from leonit.public_api.router import router as public_api_router
from leonit.reports.router import public_router as public_reports_router
from leonit.reports.router import router as reports_router
from leonit.vacancies.router import router as vacancies_router

ROUTERS: list[APIRouter] = [
    health_router,
    auth_router,
    invites_router,
    organization_router,
    vacancies_router,
    media_router,
    legal_router,
    candidates_router,
    interviews_router,
    public_router,
    room_router,
    interview_staff_router,
    evaluation_router,
    reports_router,
    public_reports_router,
    emails_router,
    assistant_router,
    api_tokens_router,
    public_api_router,
    api_docs_router,
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    try:
        yield
    finally:
        await shutdown_gateway()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LeonIT API",
        version="0.1.0",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        # На стенде API живёт за тем же доменом, что и сайт (Caddy проксирует /api);
        # локально документация открывается с самого бэкенда, и относительного
        # адреса достаточно.
        servers=[
            {
                "url": settings.PUBLIC_URL if settings.is_production else "/",
                "description": "LeonIT",
            }
        ],
        lifespan=lifespan,
        # Swagger кабинета на проде выключен; документация публичного API —
        # отдельная страница /api/docs/api (см. leonit.public_api.docs).
        docs_url=None if settings.is_production else f"{settings.API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{settings.API_PREFIX}/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router, prefix=settings.API_PREFIX)
    return app


app = create_app()
