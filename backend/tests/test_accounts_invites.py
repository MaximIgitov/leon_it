from __future__ import annotations

import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from leonit.accounts.models import Invite
from leonit.core.db import get_session_maker
from leonit.core.time import utcnow
from tests.helpers import bearer, create_invite, invite_token_from_url, register


async def test_invite_flow_register_with_role(client: AsyncClient) -> None:
    _, owner = await register(client, organization_name="Орг")
    invite = await create_invite(client, owner, role="recruiter")
    assert invite["status"] == "active"
    assert invite["url"].startswith("http")
    token = invite_token_from_url(invite["url"])

    preview = await client.get(f"/api/invites/{token}/preview")
    assert preview.status_code == 200
    assert preview.json() == {
        "organization_name": "Орг",
        "role": "recruiter",
        "email": None,
        "valid": True,
        "reason": None,
    }

    _, recruiter = await register(client, invite_token=token)
    me = (await client.get("/api/auth/me", headers=bearer(recruiter))).json()
    assert me["role"] == "recruiter"
    assert me["organization"]["name"] == "Орг"
    assert "org.members" not in me["permissions"]

    # Одноразовая ссылка исчерпана.
    listing = (await client.get("/api/organization/invites", headers=bearer(owner))).json()
    assert listing[0]["status"] == "exhausted"
    assert listing[0]["url"] is None
    again = await client.post(
        "/api/auth/register",
        json={
            "email": "x@example.com",
            "password": "correct-horse-battery",
            "full_name": "Икс",
            "invite_token": token,
        },
    )
    assert again.status_code == 422


async def test_multi_use_invite_and_revoke(client: AsyncClient) -> None:
    _, owner = await register(client)
    invite = await create_invite(
        client, owner, role="hiring_manager", max_uses=None, vacancy_scope=["v1"]
    )
    token = invite_token_from_url(invite["url"])
    await register(client, invite_token=token)
    _, second = await register(client, invite_token=token)
    assert (await client.get("/api/auth/me", headers=bearer(second))).json()["vacancy_scope"] == [
        "v1"
    ]

    revoked = await client.delete(
        f"/api/organization/invites/{invite['id']}", headers=bearer(owner)
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    preview = (await client.get(f"/api/invites/{token}/preview")).json()
    assert preview["valid"] is False and preview["reason"] == "Приглашение отозвано"
    third = await client.post(
        "/api/auth/register",
        json={
            "email": "third@example.com",
            "password": "correct-horse-battery",
            "full_name": "Третий",
            "invite_token": token,
        },
    )
    assert third.status_code == 422


async def test_expired_invite_is_rejected(client: AsyncClient) -> None:
    _, owner = await register(client)
    invite = await create_invite(client, owner, expires_in_days=1)
    token = invite_token_from_url(invite["url"])
    async with get_session_maker()() as session:
        await session.execute(
            update(Invite)
            .where(Invite.id == uuid.UUID(invite["id"]))
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
        await session.commit()
    preview = (await client.get(f"/api/invites/{token}/preview")).json()
    assert preview["valid"] is False
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "late@example.com",
            "password": "correct-horse-battery",
            "full_name": "Опоздавший",
            "invite_token": token,
        },
    )
    assert response.status_code == 422
    assert "истёк" in response.json()["detail"]


async def test_email_locked_invite(client: AsyncClient) -> None:
    _, owner = await register(client)
    invite = await create_invite(client, owner, email="Named@Example.com")
    token = invite_token_from_url(invite["url"])
    wrong = await client.post(
        "/api/auth/register",
        json={
            "email": "other@example.com",
            "password": "correct-horse-battery",
            "full_name": "Другой",
            "invite_token": token,
        },
    )
    assert wrong.status_code == 403
    _, ok = await register(client, email="named@example.com", invite_token=token)
    assert (await client.get("/api/auth/me", headers=bearer(ok))).json()["role"] == "recruiter"


async def test_logged_in_user_cannot_join_second_organization(client: AsyncClient) -> None:
    _, owner = await register(client)
    _, other = await register(client, organization_name="Другая")
    invite = await create_invite(client, owner)
    token = invite_token_from_url(invite["url"])
    response = await client.post(
        "/api/invites/accept", json={"token": token}, headers=bearer(other)
    )
    assert response.status_code == 409


async def test_unknown_invite_preview_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/invites/nope/preview")).status_code == 404


async def test_recruiter_cannot_manage_invites(client: AsyncClient) -> None:
    _, owner = await register(client)
    token = invite_token_from_url((await create_invite(client, owner))["url"])
    _, recruiter = await register(client, invite_token=token)
    response = await client.post(
        "/api/organization/invites", json={"role": "recruiter"}, headers=bearer(recruiter)
    )
    assert response.status_code == 403
    assert (
        await client.get("/api/organization/invites", headers=bearer(recruiter))
    ).status_code == 403


async def test_invite_token_is_stored_hashed(client: AsyncClient) -> None:
    _, owner = await register(client)
    invite = await create_invite(client, owner)
    token = invite_token_from_url(invite["url"])
    async with get_session_maker()() as session:
        row = await session.scalar(select(Invite).where(Invite.id == uuid.UUID(invite["id"])))
        assert row is not None
        assert row.token_hash != token
        assert len(row.token_hash) == 64
