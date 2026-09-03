"""Доменные ошибки и их отображение в HTTP.

Сервисы бросают доменные исключения и ничего не знают о FastAPI; один обработчик
превращает их в ответы с единообразным телом ``{"detail": "..."}``.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND


class PermissionDeniedError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT


class UnauthorizedError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED


class ValidationFailedError(DomainError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT


class UpstreamError(DomainError):
    """Внешний провайдер (модель, HH, Huntflow) недоступен или ответил ошибкой."""

    status_code = status.HTTP_502_BAD_GATEWAY


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
