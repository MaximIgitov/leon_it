"""Аутентификация публичного API по токену ``Authorization: Bearer leonit_…``.

Токен превращается в ``ApiActor`` — совместимый с ``Actor`` объект, которым
пользуются те же сервисы, что и кабинет: у него есть организация, «пользователь»
(автор токена — его id попадает в ``created_by``) и набор действий, выведенный
из областей токена. Бизнес-логика при этом не дублируется, а проверка прав
остаётся в одном месте — ``leonit.core.authz``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from leonit.accounts.models import MembershipRole, Organization
from leonit.api_tokens.models import ApiToken
from leonit.api_tokens.scopes import actions_for
from leonit.api_tokens.service import ApiTokenService, token_status
from leonit.candidates.router import _client_ip
from leonit.core.authz import Actor
from leonit.core.deps import DbSession
from leonit.core.errors import PermissionDeniedError, UnauthorizedError
from leonit.core.rate_limit import SlidingWindowRateLimiter

# Лимит на токен, не на адрес: интеграция ходит с одного сервера, и лимит по
# адресу либо мешал бы ей, либо был бы бесполезен.
API_RATE_LIMIT_PER_MINUTE = 600
api_rate_limiter = SlidingWindowRateLimiter(max_attempts=API_RATE_LIMIT_PER_MINUTE, window_s=60)

# Неудачные попытки аутентификации (неизвестный, отозванный, просроченный токен)
# считаются по адресу ещё до поиска в базе: лимит на токен их не покрывает —
# токена-то нет, — а перебор не должен стоить нам запроса к базе на каждую
# попытку. Как и login_rate_limiter, счётчик живёт в памяти процесса: при
# нескольких воркерах лимит действует на каждый из них отдельно.
API_AUTH_FAILURES_PER_WINDOW = 30
API_AUTH_FAILURE_WINDOW_S = 300
api_auth_failure_limiter = SlidingWindowRateLimiter(
    max_attempts=API_AUTH_FAILURES_PER_WINDOW, window_s=API_AUTH_FAILURE_WINDOW_S
)

# Отдельная схема безопасности: в OpenAPI ручки /v1 помечаются «ApiToken», а не
# сессионным JWT кабинета.
api_token_scheme = HTTPBearer(
    scheme_name="ApiToken",
    bearerFormat="leonit_<секрет>",
    description=(
        "API-токен организации: `Authorization: Bearer leonit_…`. "
        "Выпускается владельцем в разделе «Интеграции → API»."
    ),
    auto_error=False,
)


@dataclass(frozen=True)
class ApiUser:
    """Пользователь-заглушка для интеграции: сервисы пишут её id в ``created_by``."""

    id: UUID | None
    email: str
    full_name: str
    is_active: bool = True


@dataclass(frozen=True)
class ApiMembership:
    organization_id: UUID
    role: MembershipRole
    # Ограничение по вакансиям — только для нанимающего менеджера; у токена его нет.
    vacancy_scope: list[str] | None = None
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class ApiActor(Actor):
    token: ApiToken
    scopes: frozenset[str]


def build_api_actor(token: ApiToken, organization: Organization) -> ApiActor:
    scopes = frozenset(token.scopes)
    # Роль здесь номинальная (для логов и отладки): права выводятся из областей.
    role = (
        MembershipRole.recruiter
        if any(scope.endswith(":write") for scope in scopes)
        else MembershipRole.hiring_manager
    )
    return ApiActor(
        user=ApiUser(  # type: ignore[arg-type]
            id=token.created_by_user_id, email="", full_name=f"API: {token.name}"
        ),
        membership=ApiMembership(organization_id=organization.id, role=role),  # type: ignore[arg-type]
        organization=organization,
        actions=actions_for(scopes),
        token=token,
        scopes=scopes,
    )


def _too_many(retry_after_s: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(retry_after_s)},
    )


def _auth_failure(token: ApiToken | None) -> str | None:
    """Почему токен не подходит; ``None`` — токен действителен."""
    if token is None:
        return "Токен не найден"
    state = token_status(token)
    if state == "revoked":
        return "Токен отозван"
    if state == "expired":
        return "Срок действия токена истёк"
    return None


async def get_api_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(api_token_scheme)],
    session: DbSession,
) -> ApiActor:
    if credentials is None:
        raise UnauthorizedError("Нужен API-токен: Authorization: Bearer leonit_…")
    address = _client_ip(request)
    blocked = api_auth_failure_limiter.peek(address)
    if not blocked.allowed:
        raise _too_many(
            blocked.retry_after_s, "Слишком много неудачных попыток аутентификации с этого адреса"
        )
    service = ApiTokenService(session)
    token = await service.by_raw_token(credentials.credentials)
    failure = _auth_failure(token)
    if failure is not None:
        api_auth_failure_limiter.check(address)
        raise UnauthorizedError(failure)
    assert token is not None
    decision = api_rate_limiter.check(str(token.id))
    if not decision.allowed:
        raise _too_many(
            decision.retry_after_s, f"Лимит {API_RATE_LIMIT_PER_MINUTE} запросов в минуту исчерпан"
        )
    organization = await session.get(Organization, token.organization_id)
    if organization is None:
        raise UnauthorizedError("Организация токена не найдена")
    await service.touch(token)
    return build_api_actor(token, organization)


CurrentApiActor = Annotated[ApiActor, Depends(get_api_actor)]


def require_scope(scope: str) -> Callable[..., Awaitable[ApiActor]]:
    """Зависимость: токен должен иметь область ``scope``."""

    async def dependency(actor: CurrentApiActor) -> ApiActor:
        if scope not in actor.scopes:
            raise PermissionDeniedError(f"Токену не хватает области {scope}")
        return actor

    return dependency
