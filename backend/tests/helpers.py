"""Общие помощники для API-тестов."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def register(
    client: AsyncClient,
    *,
    email: str | None = None,
    password: str = "correct-horse-battery",
    full_name: str = "Тест Тестов",
    organization_name: str | None = "Тестовая организация",
    invite_token: str | None = None,
) -> tuple[str, str]:
    """Зарегистрировать пользователя, вернуть (email, access_token)."""
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    payload = {"email": email, "password": password, "full_name": full_name}
    if invite_token:
        payload["invite_token"] = invite_token
    elif organization_name:
        payload["organization_name"] = organization_name
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return email, response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_invite(client: AsyncClient, token: str, **overrides) -> dict:
    payload = {"role": "recruiter", **overrides}
    response = await client.post("/api/organization/invites", json=payload, headers=bearer(token))
    assert response.status_code == 201, response.text
    return response.json()


def invite_token_from_url(url: str) -> str:
    return url.rsplit("token=", 1)[1]
