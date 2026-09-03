from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from leonit.accounts.deps import CurrentActor, CurrentUser
from leonit.accounts.models import Membership, User
from leonit.accounts.schemas import (
    AcceptInviteRequest,
    AuditEntryOut,
    ChangePasswordRequest,
    InviteCreate,
    InviteOut,
    InvitePreview,
    LoginRequest,
    MemberOut,
    MemberUpdate,
    MeResponse,
    OrganizationOut,
    OrganizationUpdate,
    RegisterRequest,
    TokenResponse,
)
from leonit.accounts.security import create_access_token
from leonit.accounts.service import AccountsService, invite_to_out
from leonit.core.authz import _ROLE_ACTIONS, Actor
from leonit.core.deps import DbSession, SettingsDep
from leonit.core.rate_limit import SlidingWindowRateLimiter
from leonit.core.time import aware

auth_router = APIRouter(prefix="/auth", tags=["auth"])
invites_router = APIRouter(prefix="/invites", tags=["invites"])
organization_router = APIRouter(prefix="/organization", tags=["organization"])

login_rate_limiter = SlidingWindowRateLimiter(max_attempts=10, window_s=300)
# 50/час на адрес: онбординг команды из офиса за одним NAT не должен упираться.
register_rate_limiter = SlidingWindowRateLimiter(max_attempts=50, window_s=3600)
preview_rate_limiter = SlidingWindowRateLimiter(max_attempts=60, window_s=300)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _too_many(retry_after_s: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Слишком много попыток, попробуйте позже",
        headers={"Retry-After": str(retry_after_s)},
    )


def _token(settings, user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(
            settings, user_id=user.id, token_version=user.token_version
        )
    )


def _me(actor: Actor) -> MeResponse:
    return MeResponse(
        id=str(actor.user.id),
        email=actor.user.email,
        full_name=actor.user.full_name,
        role=actor.role.value,  # type: ignore[arg-type]
        vacancy_scope=actor.membership.vacancy_scope,
        organization=OrganizationOut(
            id=str(actor.organization.id),
            name=actor.organization.name,
            retention_days=actor.organization.retention_days,
        ),
        permissions=sorted(_ROLE_ACTIONS[actor.role.value]),
    )


def _member(membership: Membership, user: User) -> MemberOut:
    return MemberOut(
        id=str(membership.id),
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=membership.role.value,  # type: ignore[arg-type]
        is_active=membership.is_active,
        vacancy_scope=membership.vacancy_scope,
        created_at=aware(membership.created_at),  # type: ignore[arg-type]
        last_login_at=aware(user.last_login_at),
    )


# ------------------------------------------------------------------------ auth


@auth_router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, session: DbSession, settings: SettingsDep, request: Request
) -> TokenResponse:
    decision = register_rate_limiter.check(_client_ip(request))
    if not decision.allowed:
        raise _too_many(decision.retry_after_s)
    user = await AccountsService(session).register(payload)
    return _token(settings, user)


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, session: DbSession, settings: SettingsDep, request: Request
) -> TokenResponse:
    # Бюджет на пару (адрес, e-mail): перебор одного аккаунта и спрей с одного
    # адреса упираются в лимит, соседи за тем же NAT — нет.
    key = f"{_client_ip(request)}:{payload.email.lower()}"
    decision = login_rate_limiter.check(key)
    if not decision.allowed:
        raise _too_many(decision.retry_after_s)
    user = await AccountsService(session).login(payload)
    login_rate_limiter.reset(key)
    return _token(settings, user)


@auth_router.get("/me", response_model=MeResponse)
async def me(actor: CurrentActor) -> MeResponse:
    return _me(actor)


@auth_router.post("/change-password", response_model=TokenResponse)
async def change_password(
    payload: ChangePasswordRequest, user: CurrentUser, session: DbSession, settings: SettingsDep
) -> TokenResponse:
    await AccountsService(session).change_password(
        user, payload.current_password, payload.new_password
    )
    return _token(settings, user)


@auth_router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: CurrentUser, session: DbSession) -> None:
    await AccountsService(session).logout_everywhere(user)


# --------------------------------------------------------------------- invites


@invites_router.get("/{token}/preview", response_model=InvitePreview)
async def preview_invite(token: str, session: DbSession, request: Request) -> InvitePreview:
    decision = preview_rate_limiter.check(_client_ip(request))
    if not decision.allowed:
        raise _too_many(decision.retry_after_s)
    return await AccountsService(session).preview_invite(token)


@invites_router.post("/accept", response_model=MeResponse)
async def accept_invite(
    payload: AcceptInviteRequest, user: CurrentUser, session: DbSession
) -> MeResponse:
    service = AccountsService(session)
    await service.accept_invite(user, payload.token)
    actor = await service.get_actor(user)
    assert actor is not None
    return _me(actor)


# ---------------------------------------------------------------- organization


@organization_router.get("", response_model=OrganizationOut)
async def get_organization(actor: CurrentActor) -> OrganizationOut:
    return _me(actor).organization


@organization_router.patch("", response_model=OrganizationOut)
async def update_organization(
    payload: OrganizationUpdate, actor: CurrentActor, session: DbSession
) -> OrganizationOut:
    organization = await AccountsService(session).update_organization(actor, payload)
    return OrganizationOut(
        id=str(organization.id), name=organization.name, retention_days=organization.retention_days
    )


@organization_router.get("/members", response_model=list[MemberOut])
async def list_members(actor: CurrentActor, session: DbSession) -> list[MemberOut]:
    rows = await AccountsService(session).list_members(actor)
    return [_member(membership, user) for membership, user in rows]


@organization_router.patch("/members/{membership_id}", response_model=MemberOut)
async def update_member(
    membership_id: UUID, payload: MemberUpdate, actor: CurrentActor, session: DbSession
) -> MemberOut:
    membership, user = await AccountsService(session).update_member(actor, membership_id, payload)
    return _member(membership, user)


@organization_router.post("/members/{membership_id}/deactivate", response_model=MemberOut)
async def deactivate_member(
    membership_id: UUID, actor: CurrentActor, session: DbSession
) -> MemberOut:
    membership, user = await AccountsService(session).deactivate_member(actor, membership_id)
    return _member(membership, user)


@organization_router.post("/members/{membership_id}/reactivate", response_model=MemberOut)
async def reactivate_member(
    membership_id: UUID, actor: CurrentActor, session: DbSession
) -> MemberOut:
    membership, user = await AccountsService(session).reactivate_member(actor, membership_id)
    return _member(membership, user)


@organization_router.get("/invites", response_model=list[InviteOut])
async def list_invites(actor: CurrentActor, session: DbSession) -> list[InviteOut]:
    invites = await AccountsService(session).list_invites(actor)
    return [invite_to_out(invite) for invite in invites]


@organization_router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreate, actor: CurrentActor, session: DbSession
) -> InviteOut:
    invite, token = await AccountsService(session).create_invite(actor, payload)
    return invite_to_out(invite, token)


@organization_router.delete("/invites/{invite_id}", response_model=InviteOut)
async def revoke_invite(invite_id: UUID, actor: CurrentActor, session: DbSession) -> InviteOut:
    invite = await AccountsService(session).revoke_invite(actor, invite_id)
    return invite_to_out(invite)


@organization_router.get("/audit", response_model=list[AuditEntryOut])
async def list_audit(actor: CurrentActor, session: DbSession) -> list[AuditEntryOut]:
    rows = await AccountsService(session).list_audit(actor)
    return [
        AuditEntryOut(
            id=str(entry.id),
            actor_user_id=str(entry.actor_user_id) if entry.actor_user_id else None,
            actor_email=email,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            details=entry.details,
            created_at=aware(entry.created_at),  # type: ignore[arg-type]
        )
        for entry, email in rows
    ]
