"""Регистрация, вход, приглашения и участники организации."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.accounts.models import (
    AccessAuditLog,
    Invite,
    Membership,
    MembershipRole,
    Organization,
    User,
)
from leonit.accounts.schemas import (
    InviteCreate,
    InviteOut,
    InvitePreview,
    LoginRequest,
    MemberUpdate,
    OrganizationUpdate,
    RegisterRequest,
)
from leonit.accounts.security import (
    DUMMY_PASSWORD_HASH,
    generate_link_token,
    hash_link_token,
    hash_password,
    verify_password,
)
from leonit.core.authz import Actor, authorize
from leonit.core.config import get_settings
from leonit.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnauthorizedError,
    ValidationFailedError,
)
from leonit.core.time import aware, utcnow


def invite_status(invite: Invite) -> str:
    if invite.revoked_at is not None:
        return "revoked"
    if aware(invite.expires_at) < utcnow():
        return "expired"
    if invite.max_uses is not None and invite.uses_count >= invite.max_uses:
        return "exhausted"
    return "active"


def invite_url(token: str) -> str:
    return f"{get_settings().PUBLIC_URL}/join?token={token}"


class AccountsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------------------------------------------------------- lookups

    async def get_user_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def get_user(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_membership(self, user_id: UUID) -> Membership | None:
        return await self.session.scalar(
            select(Membership)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at.asc())
        )

    async def get_actor(self, user: User) -> Actor | None:
        membership = await self.get_membership(user.id)
        if membership is None or not membership.is_active:
            return None
        organization = await self.session.get(Organization, membership.organization_id)
        if organization is None:
            return None
        return Actor(user=user, membership=membership, organization=organization)

    # ------------------------------------------------------------------ audit

    async def audit(
        self,
        organization_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        target_type: str,
        target_id: str | None = None,
        **details: Any,
    ) -> None:
        self.session.add(
            AccessAuditLog(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
        )

    # ------------------------------------------------------------------- auth

    async def register(self, payload: RegisterRequest) -> User:
        email = payload.email.lower()
        if await self.get_user_by_email(email):
            raise ConflictError("Пользователь с таким e-mail уже зарегистрирован")

        invite: Invite | None = None
        if payload.invite_token:
            invite = await self._valid_invite(payload.invite_token, email=email)

        user = User(
            email=email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            last_login_at=utcnow(),
        )
        self.session.add(user)
        await self.session.flush()

        if invite is not None:
            await self._accept(invite, user)
        else:
            name = payload.organization_name or f"Компания {payload.full_name}"
            organization = Organization(name=name, created_by_user_id=user.id)
            self.session.add(organization)
            await self.session.flush()
            self.session.add(
                Membership(
                    organization_id=organization.id, user_id=user.id, role=MembershipRole.owner
                )
            )
            await self.audit(organization.id, user.id, "organization.created", "organization")
        await self.session.commit()
        return user

    async def login(self, payload: LoginRequest) -> User:
        user = await self.get_user_by_email(payload.email)
        if user is None:
            # Та же работа PBKDF2, что и для настоящей проверки: по времени ответа
            # нельзя понять, существует ли аккаунт.
            verify_password(payload.password, DUMMY_PASSWORD_HASH)
            raise UnauthorizedError("Неверный e-mail или пароль")
        if not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedError("Неверный e-mail или пароль")
        if not user.is_active:
            raise UnauthorizedError("Аккаунт отключён")
        user.last_login_at = utcnow()
        await self.session.commit()
        return user

    async def change_password(self, user: User, current: str, new: str) -> None:
        if not verify_password(current, user.hashed_password):
            raise UnauthorizedError("Текущий пароль указан неверно")
        user.hashed_password = hash_password(new)
        user.token_version += 1
        await self.session.commit()

    async def logout_everywhere(self, user: User) -> None:
        user.token_version += 1
        await self.session.commit()

    # ---------------------------------------------------------------- invites

    async def create_invite(self, actor: Actor, payload: InviteCreate) -> tuple[Invite, str]:
        authorize(actor, "org.invites")
        if payload.role == "owner" and actor.role != MembershipRole.owner:
            raise PermissionDeniedError("Пригласить владельца может только владелец")
        if payload.vacancy_scope is not None and payload.role != "hiring_manager":
            raise ValidationFailedError(
                "Ограничение по вакансиям применимо только к нанимающему менеджеру"
            )
        token = generate_link_token()
        invite = Invite(
            organization_id=actor.organization_id,
            token_hash=hash_link_token(token),
            role=MembershipRole(payload.role),
            email=payload.email.lower() if payload.email else None,
            vacancy_scope=payload.vacancy_scope,
            expires_at=utcnow() + timedelta(days=payload.expires_in_days),
            max_uses=payload.max_uses,
            created_by_user_id=actor.user.id,
        )
        self.session.add(invite)
        await self.session.flush()
        await self.audit(
            actor.organization_id,
            actor.user.id,
            "invite.created",
            "invite",
            str(invite.id),
            role=payload.role,
            email=invite.email,
            expires_in_days=payload.expires_in_days,
            max_uses=payload.max_uses,
        )
        await self.session.commit()
        return invite, token

    async def list_invites(self, actor: Actor) -> list[Invite]:
        authorize(actor, "org.invites")
        rows = await self.session.scalars(
            select(Invite)
            .where(Invite.organization_id == actor.organization_id)
            .order_by(Invite.created_at.desc())
        )
        return list(rows)

    async def revoke_invite(self, actor: Actor, invite_id: UUID) -> Invite:
        authorize(actor, "org.invites")
        invite = await self.session.get(Invite, invite_id)
        if invite is None or invite.organization_id != actor.organization_id:
            raise NotFoundError("Приглашение не найдено")
        if invite.revoked_at is None:
            invite.revoked_at = utcnow()
            await self.audit(
                actor.organization_id, actor.user.id, "invite.revoked", "invite", str(invite.id)
            )
            await self.session.commit()
        return invite

    async def preview_invite(self, token: str) -> InvitePreview:
        invite = await self.session.scalar(
            select(Invite).where(Invite.token_hash == hash_link_token(token))
        )
        if invite is None:
            raise NotFoundError("Приглашение не найдено")
        organization = await self.session.get(Organization, invite.organization_id)
        status = invite_status(invite)
        reasons = {
            "expired": "Срок действия приглашения истёк",
            "revoked": "Приглашение отозвано",
            "exhausted": "Приглашение уже использовано",
        }
        return InvitePreview(
            organization_name=organization.name if organization else "",
            role=invite.role.value,
            email=invite.email,
            valid=status == "active",
            reason=reasons.get(status),
        )

    async def accept_invite(self, user: User, token: str) -> Membership:
        invite = await self._valid_invite(token, email=user.email)
        membership = await self._accept(invite, user)
        await self.session.commit()
        return membership

    async def _valid_invite(self, token: str, *, email: str) -> Invite:
        invite = await self.session.scalar(
            select(Invite).where(Invite.token_hash == hash_link_token(token))
        )
        if invite is None:
            raise NotFoundError("Приглашение не найдено — проверьте ссылку")
        status = invite_status(invite)
        if status != "active":
            messages = {
                "expired": "Срок действия приглашения истёк — попросите новую ссылку",
                "revoked": "Приглашение отозвано",
                "exhausted": "Приглашение уже использовано — попросите новую ссылку",
            }
            raise ValidationFailedError(messages[status])
        if invite.email and invite.email != email.lower():
            raise PermissionDeniedError("Это приглашение выписано на другой e-mail")
        return invite

    async def _accept(self, invite: Invite, user: User) -> Membership:
        existing = await self.get_membership(user.id)
        if existing is not None:
            if existing.organization_id == invite.organization_id:
                raise ConflictError("Вы уже состоите в этой организации")
            raise ConflictError("Аккаунт уже состоит в другой организации")
        membership = Membership(
            organization_id=invite.organization_id,
            user_id=user.id,
            role=invite.role,
            vacancy_scope=invite.vacancy_scope,
            invited_by_user_id=invite.created_by_user_id,
        )
        self.session.add(membership)
        invite.uses_count += 1
        invite.last_accepted_at = utcnow()
        await self.audit(
            invite.organization_id,
            user.id,
            "invite.accepted",
            "invite",
            str(invite.id),
            role=invite.role.value,
            email=user.email,
        )
        await self.session.flush()
        return membership

    # ---------------------------------------------------------------- members

    async def list_members(self, actor: Actor) -> list[tuple[Membership, User]]:
        authorize(actor, "org.members")
        rows = await self.session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == actor.organization_id)
            .order_by(Membership.created_at.asc())
        )
        return [(membership, user) for membership, user in rows.all()]

    async def _member(self, actor: Actor, membership_id: UUID) -> tuple[Membership, User]:
        membership = await self.session.get(Membership, membership_id)
        if membership is None or membership.organization_id != actor.organization_id:
            raise NotFoundError("Участник не найден")
        user = await self.session.get(User, membership.user_id)
        assert user is not None
        return membership, user

    async def _active_owner_count(self, organization_id: UUID) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.role == MembershipRole.owner,
                    Membership.is_active.is_(True),
                )
            )
            or 0
        )

    async def _guard_last_owner(self, membership: Membership) -> None:
        if (
            membership.role == MembershipRole.owner
            and membership.is_active
            and await self._active_owner_count(membership.organization_id) <= 1
        ):
            raise ConflictError("В организации должен остаться хотя бы один владелец")

    async def update_member(
        self, actor: Actor, membership_id: UUID, payload: MemberUpdate
    ) -> tuple[Membership, User]:
        authorize(actor, "org.members")
        membership, user = await self._member(actor, membership_id)
        changed: dict[str, Any] = {}
        if payload.role is not None and payload.role != membership.role.value:
            await self._guard_last_owner(membership)
            changed["role"] = {"from": membership.role.value, "to": payload.role}
            membership.role = MembershipRole(payload.role)
            if membership.role != MembershipRole.hiring_manager:
                membership.vacancy_scope = None
        if "vacancy_scope" in payload.model_fields_set:
            if payload.vacancy_scope is not None and (
                membership.role != MembershipRole.hiring_manager
            ):
                raise ValidationFailedError(
                    "Ограничение по вакансиям применимо только к нанимающему менеджеру"
                )
            changed["vacancy_scope"] = payload.vacancy_scope
            membership.vacancy_scope = payload.vacancy_scope
        if changed:
            # Права поменялись — старые сессии участника должны перезапросить их.
            user.token_version += 1
            await self.audit(
                actor.organization_id,
                actor.user.id,
                "member.updated",
                "membership",
                str(membership.id),
                **changed,
            )
            await self.session.commit()
        return membership, user

    async def deactivate_member(self, actor: Actor, membership_id: UUID) -> tuple[Membership, User]:
        authorize(actor, "org.members")
        membership, user = await self._member(actor, membership_id)
        if membership.user_id == actor.user.id:
            raise ConflictError("Нельзя отозвать доступ у самого себя")
        if membership.is_active:
            await self._guard_last_owner(membership)
            membership.is_active = False
            user.token_version += 1
            await self.audit(
                actor.organization_id,
                actor.user.id,
                "member.deactivated",
                "membership",
                str(membership.id),
                email=user.email,
            )
            await self.session.commit()
        return membership, user

    async def reactivate_member(self, actor: Actor, membership_id: UUID) -> tuple[Membership, User]:
        authorize(actor, "org.members")
        membership, user = await self._member(actor, membership_id)
        if not membership.is_active:
            membership.is_active = True
            await self.audit(
                actor.organization_id,
                actor.user.id,
                "member.reactivated",
                "membership",
                str(membership.id),
                email=user.email,
            )
            await self.session.commit()
        return membership, user

    # ----------------------------------------------------------- organization

    async def update_organization(self, actor: Actor, payload: OrganizationUpdate) -> Organization:
        authorize(actor, "org.write")
        organization = actor.organization
        changed: dict[str, Any] = {}
        if payload.name is not None and payload.name != organization.name:
            changed["name"] = {"from": organization.name, "to": payload.name}
            organization.name = payload.name
        if (
            payload.retention_days is not None
            and payload.retention_days != organization.retention_days
        ):
            changed["retention_days"] = {
                "from": organization.retention_days,
                "to": payload.retention_days,
            }
            organization.retention_days = payload.retention_days
        if changed:
            await self.audit(
                organization.id, actor.user.id, "organization.updated", "organization", **changed
            )
            await self.session.commit()
        return organization

    async def list_audit(
        self, actor: Actor, limit: int = 100
    ) -> list[tuple[AccessAuditLog, str | None]]:
        authorize(actor, "org.audit")
        rows = await self.session.execute(
            select(AccessAuditLog, User.email)
            .outerjoin(User, User.id == AccessAuditLog.actor_user_id)
            .where(AccessAuditLog.organization_id == actor.organization_id)
            .order_by(AccessAuditLog.created_at.desc())
            .limit(limit)
        )
        return [(entry, email) for entry, email in rows.all()]


def invite_to_out(invite: Invite, token: str | None = None) -> InviteOut:
    return InviteOut(
        id=str(invite.id),
        role=invite.role.value,
        email=invite.email,
        vacancy_scope=invite.vacancy_scope,
        expires_at=aware(invite.expires_at),  # type: ignore[arg-type]
        max_uses=invite.max_uses,
        uses_count=invite.uses_count,
        revoked_at=aware(invite.revoked_at),
        created_at=aware(invite.created_at),  # type: ignore[arg-type]
        status=invite_status(invite),  # type: ignore[arg-type]
        url=invite_url(token) if token else None,
    )
