from __future__ import annotations

import pytest
from httpx import AsyncClient

from leonit.accounts.router import login_rate_limiter, register_rate_limiter
from tests.helpers import bearer, register


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    login_rate_limiter.clear()
    register_rate_limiter.clear()
    yield
    login_rate_limiter.clear()
    register_rate_limiter.clear()


async def test_register_creates_organization_with_owner(client: AsyncClient) -> None:
    email, token = await register(client, organization_name="Example IT")
    response = await client.get("/api/auth/me", headers=bearer(token))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert body["role"] == "owner"
    assert body["organization"]["name"] == "Example IT"
    assert "org.members" in body["permissions"]
    assert body["vacancy_scope"] is None


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    email, _ = await register(client)
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct-horse-battery", "full_name": "Дубль"},
    )
    assert response.status_code == 409


async def test_login_and_wrong_password(client: AsyncClient) -> None:
    email, _ = await register(client, password="correct-horse-battery")
    ok = await client.post(
        "/api/auth/login", json={"email": email, "password": "correct-horse-battery"}
    )
    assert ok.status_code == 200
    assert ok.json()["token_type"] == "bearer"
    bad = await client.post("/api/auth/login", json={"email": email, "password": "wrong-pass"})
    assert bad.status_code == 401
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"}
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == bad.json()["detail"]


async def test_login_rate_limit_per_ip_and_email(client: AsyncClient) -> None:
    email, _ = await register(client)
    for _ in range(10):
        await client.post("/api/auth/login", json={"email": email, "password": "wrong-pass"})
    blocked = await client.post("/api/auth/login", json={"email": email, "password": "wrong-pass"})
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"]


async def test_me_requires_token(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me", headers=bearer("garbage"))).status_code == 401


async def test_change_password_invalidates_old_sessions(client: AsyncClient) -> None:
    email, token = await register(client, password="correct-horse-battery")
    response = await client.post(
        "/api/auth/change-password",
        json={"current_password": "correct-horse-battery", "new_password": "new-secret-pass"},
        headers=bearer(token),
    )
    assert response.status_code == 200
    new_token = response.json()["access_token"]
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
    assert (await client.get("/api/auth/me", headers=bearer(new_token))).status_code == 200
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "new-secret-pass"}
    )
    assert login.status_code == 200


async def test_logout_all_invalidates_sessions(client: AsyncClient) -> None:
    _, token = await register(client)
    assert (await client.post("/api/auth/logout-all", headers=bearer(token))).status_code == 204
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
