"""Выпуск, список и отзыв API-токенов организации."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.accounts.models import User
from leonit.accounts.service import AccountsService
from leonit.api_tokens.models import ApiToken
from leonit.api_tokens.schemas import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from leonit.api_tokens.scopes import (
    SCOPE_ACTIONS,
    TOKEN_PREFIX,
    display_prefix,
    generate_api_token,
    hash_api_token,
)
from leonit.core.authz import Actor, authorize, can
from leonit.core.errors import NotFoundError, PermissionDeniedError
from leonit.core.time import aware, utcnow

# Как часто фиксировать использование токена: чаще — лишняя запись на каждый
# запрос, реже — владелец не поймёт, живой ли токен.
LAST_USED_RESOLUTION = timedelta(minutes=1)


def token_status(token: ApiToken) -> str:
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and aware(token.expires_at) < utcnow():  # type: ignore[operator]
        return "expired"
    return "active"


def token_out(token: ApiToken, created_by_email: str | None = None) -> ApiTokenOut:
    return ApiTokenOut(
        id=str(token.id),
        name=token.name,
        token_prefix=token.token_prefix,
        scopes=list(token.scopes),
        created_by_user_id=str(token.created_by_user_id) if token.created_by_user_id else None,
        created_by_email=created_by_email,
        created_at=aware(token.created_at),  # type: ignore[arg-type]
        expires_at=aware(token.expires_at),
        last_used_at=aware(token.last_used_at),
        revoked_at=aware(token.revoked_at),
        status=token_status(token),  # type: ignore[arg-type]
    )


def token_created(token: ApiToken, raw: str, created_by_email: str | None) -> ApiTokenCreated:
    return ApiTokenCreated(**token_out(token, created_by_email).model_dump(), token=raw)


class ApiTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, actor: Actor, payload: ApiTokenCreate) -> tuple[ApiToken, str]:
        authorize(actor, "api_tokens.manage")
        # Токен не может уметь больше своего создателя: иначе через него можно
        # было бы обойти собственные ограничения.
        for scope in payload.scopes:
            for action in SCOPE_ACTIONS[scope]:
                if not can(actor, action):
                    raise PermissionDeniedError(f"Область {scope} шире ваших прав")
        raw = generate_api_token()
        token = ApiToken(
            organization_id=actor.organization_id,
            name=payload.name,
            token_prefix=display_prefix(raw),
            token_hash=hash_api_token(raw),
            scopes=list(payload.scopes),
            created_by_user_id=actor.user.id,
            expires_at=(
                utcnow() + timedelta(days=payload.expires_in_days)
                if payload.expires_in_days
                else None
            ),
        )
        self.session.add(token)
        await self.session.flush()
        await AccountsService(self.session).audit(
            actor.organization_id,
            actor.user.id,
            "api_token.created",
            "api_token",
            str(token.id),
            name=token.name,
            scopes=list(token.scopes),
            expires_in_days=payload.expires_in_days,
        )
        await self.session.commit()
        return token, raw

    async def list(self, actor: Actor) -> list[tuple[ApiToken, str | None]]:
        authorize(actor, "api_tokens.manage")
        rows = await self.session.execute(
            select(ApiToken, User.email)
            .outerjoin(User, User.id == ApiToken.created_by_user_id)
            .where(ApiToken.organization_id == actor.organization_id)
            .order_by(ApiToken.created_at.desc())
        )
        return [(token, email) for token, email in rows.all()]

    async def revoke(self, actor: Actor, token_id: UUID) -> ApiToken:
        authorize(actor, "api_tokens.manage")
        token = await self.session.get(ApiToken, token_id)
        if token is None or token.organization_id != actor.organization_id:
            raise NotFoundError("Токен не найден")
        if token.revoked_at is None:
            token.revoked_at = utcnow()
            await AccountsService(self.session).audit(
                actor.organization_id,
                actor.user.id,
                "api_token.revoked",
                "api_token",
                str(token.id),
                name=token.name,
            )
            await self.session.commit()
        return token

    # ---------------------------------------------------------- аутентификация

    async def by_raw_token(self, raw: str) -> ApiToken | None:
        if not raw.startswith(TOKEN_PREFIX):
            return None
        return await self.session.scalar(
            select(ApiToken).where(ApiToken.token_hash == hash_api_token(raw))
        )

    async def touch(self, token: ApiToken) -> None:
        """Отметить использование, но не чаще ``LAST_USED_RESOLUTION``."""
        now = utcnow()
        last = aware(token.last_used_at)
        if last is not None and now - last < LAST_USED_RESOLUTION:
            return
        token.last_used_at = now
        await self.session.commit()
