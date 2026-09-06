"""Доменные ошибки и их отображение в HTTP.

Сервисы бросают доменные исключения и ничего не знают о FastAPI; один обработчик
превращает их в ответы с единообразным телом ``{"detail": "..."}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class DomainError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    # Машиночитаемый код для клиента (например, ``runner_disabled``); None — только detail.
    code: str | None = None

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


# Подписи полей для сообщений об ошибках валидации: пользователь видит «E-mail»,
# а не ``body.email``.
FIELD_LABELS: dict[str, str] = {
    "email": "E-mail",
    "emails": "E-mail",
    "password": "Пароль",
    "full_name": "Имя и фамилия",
    "name": "Название",
    "title": "Название",
    "organization": "Компания",
    "organization_name": "Компания",
    "text": "Текст",
    "url": "Ссылка",
    "phone": "Телефон",
    "days": "Срок",
    "label": "Подпись",
    "vacancy_id": "Вакансия",
    "candidate_id": "Кандидат",
    "token": "Токен",
}

_RANGE_TYPES = {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}
_NUMBER_TYPES = {"int_parsing", "int_type", "float_parsing", "float_type", "int_from_float"}


def _reason(item: dict[str, Any]) -> str:
    kind = str(item.get("type", ""))
    msg = str(item.get("msg", ""))
    ctx = item.get("ctx") or {}
    if kind == "missing":
        return "обязательное поле"
    if "email" in msg.lower():
        return "некорректный адрес электронной почты"
    if kind == "string_too_short":
        return f"не короче {ctx.get('min_length')} символов"
    if kind == "string_too_long":
        return f"не длиннее {ctx.get('max_length')} символов"
    if kind in _NUMBER_TYPES:
        return "нужно число"
    if kind in _RANGE_TYPES:
        return "значение вне допустимого диапазона"
    if kind == "uuid_parsing":
        return "неверный идентификатор"
    if kind in {"enum", "literal_error"}:
        return "недопустимое значение"
    if kind == "json_invalid":
        return "неверный формат данных"
    if kind == "url_parsing":
        return "некорректная ссылка"
    if kind == "bool_parsing":
        return "ожидается да или нет"
    return msg or "некорректное значение"


def describe_validation_errors(errors: list[dict[str, Any]]) -> str:
    """Список ошибок Pydantic → одна человеческая фраза для формы или чата.

    ``[{"loc": ["body", "email"], "msg": "value is not a valid email address…"}]`` →
    «Проверьте данные — E-mail: некорректный адрес электронной почты».
    """
    parts: list[str] = []
    for item in errors[:5]:
        loc = [str(p) for p in item.get("loc", ()) if str(p) not in {"body", "query", "path"}]
        field = loc[-1] if loc else ""
        label = FIELD_LABELS.get(field, field.replace("_", " ")) or "поле"
        parts.append(f"{label}: {_reason(item)}")
    if not parts:
        return "Проверьте введённые данные"
    return "Проверьте данные — " + "; ".join(parts)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, error: DomainError) -> JSONResponse:
        content: dict[str, str] = {"detail": error.detail}
        if error.code:
            content["code"] = error.code
        return JSONResponse(status_code=error.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        # ``detail`` остаётся списком (клиенты и тесты смотрят ``loc``), а ``message``
        # — готовая фраза, которую фронтенд показывает вместо кода ошибки.
        errors = jsonable_encoder(error.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": errors, "message": describe_validation_errors(errors)},
        )
