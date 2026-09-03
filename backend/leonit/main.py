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

from leonit.core.config import get_settings
from leonit.core.db import dispose_engine
from leonit.core.errors import install_error_handlers
from leonit.core.logging import setup_logging
from leonit.core.observability import RequestContextMiddleware
from leonit.core.security_headers import SecurityHeadersMiddleware
from leonit.health.router import router as health_router

ROUTERS: list[APIRouter] = [health_router]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    try:
        yield
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LeonIT API",
        version="0.1.0",
        lifespan=lifespan,
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
