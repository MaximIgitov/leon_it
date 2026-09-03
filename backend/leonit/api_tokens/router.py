from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from leonit.accounts.deps import CurrentActor
from leonit.api_tokens.schemas import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from leonit.api_tokens.service import ApiTokenService, token_created, token_out
from leonit.core.deps import DbSession

router = APIRouter(prefix="/organization/api-tokens", tags=["organization"])


@router.get("", response_model=list[ApiTokenOut])
async def list_api_tokens(actor: CurrentActor, session: DbSession) -> list[ApiTokenOut]:
    rows = await ApiTokenService(session).list(actor)
    return [token_out(token, email) for token, email in rows]


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_api_token(
    payload: ApiTokenCreate, actor: CurrentActor, session: DbSession
) -> ApiTokenCreated:
    token, raw = await ApiTokenService(session).create(actor, payload)
    return token_created(token, raw, actor.user.email)


@router.delete("/{token_id}", response_model=ApiTokenOut)
async def revoke_api_token(token_id: UUID, actor: CurrentActor, session: DbSession) -> ApiTokenOut:
    token = await ApiTokenService(session).revoke(actor, token_id)
    return token_out(token)
