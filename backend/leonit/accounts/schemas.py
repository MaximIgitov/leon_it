from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Role = Literal["owner", "recruiter", "hiring_manager"]
InvitableRole = Literal["recruiter", "hiring_manager", "owner"]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    # Без приглашения создаётся новая организация с этим названием.
    organization_name: str | None = Field(default=None, max_length=255)
    # С приглашением — вступление в существующую организацию с ролью из него.
    invite_token: str | None = Field(default=None, max_length=128)

    @field_validator("full_name", "organization_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OrganizationOut(BaseModel):
    id: str
    name: str
    retention_days: int


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    retention_days: int | None = Field(default=None, ge=7, le=3650)


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None
    role: Role
    vacancy_scope: list[str] | None
    organization: OrganizationOut
    # Что можно этой роли — фронтенд строит навигацию по этому списку, а не по роли.
    permissions: list[str]


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: EmailStr
    full_name: str | None
    role: Role
    is_active: bool
    vacancy_scope: list[str] | None
    created_at: datetime
    last_login_at: datetime | None


class MemberUpdate(BaseModel):
    role: Role | None = None
    vacancy_scope: list[str] | None = None


class InviteCreate(BaseModel):
    role: InvitableRole
    email: EmailStr | None = None
    expires_in_days: int = Field(default=7, ge=1, le=30)
    # None — многоразовая ссылка до истечения срока.
    max_uses: int | None = Field(default=1, ge=1, le=1000)
    vacancy_scope: list[str] | None = None


class InviteOut(BaseModel):
    id: str
    role: Role
    email: EmailStr | None
    vacancy_scope: list[str] | None
    expires_at: datetime
    max_uses: int | None
    uses_count: int
    revoked_at: datetime | None
    created_at: datetime
    status: Literal["active", "expired", "revoked", "exhausted"]
    # Заполняется только в ответе на создание: сам токен нигде не хранится.
    url: str | None = None


class InvitePreview(BaseModel):
    organization_name: str
    role: Role
    email: EmailStr | None
    valid: bool
    reason: str | None = None


class AcceptInviteRequest(BaseModel):
    token: str = Field(max_length=128)


class AuditEntryOut(BaseModel):
    id: str
    actor_user_id: str | None
    actor_email: EmailStr | None
    action: str
    target_type: str
    target_id: str | None
    details: dict
    created_at: datetime
