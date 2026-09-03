"""Зависимости FastAPI: текущий пользователь и участник организации."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from leonit.accounts.models import User
from leonit.accounts.security import decode_access_token
from leonit.accounts.service import AccountsService
from leonit.core.authz import Actor
from leonit.core.deps import DbSession, SettingsDep
from leonit.core.errors import PermissionDeniedError, UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
    settings: SettingsDep,
) -> User:
    if credentials is None:
        raise UnauthorizedError("Требуется вход")
    decoded = decode_access_token(settings, credentials.credentials)
    if decoded is None:
        raise UnauthorizedError("Сессия недействительна, войдите заново")
    user_id, token_version = decoded
    user = await AccountsService(session).get_user(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Аккаунт отключён")
    if user.token_version != token_version:
        raise UnauthorizedError("Права изменились, войдите заново")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_actor(user: CurrentUser, session: DbSession) -> Actor:
    actor = await AccountsService(session).get_actor(user)
    if actor is None:
        raise PermissionDeniedError("Доступ к организации отозван")
    return actor


CurrentActor = Annotated[Actor, Depends(get_current_actor)]
