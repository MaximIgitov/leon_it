from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

from leonit.core.authz import Actor, can
from tests.helpers import bearer, create_invite, invite_token_from_url, register


async def _org_with_recruiter(client: AsyncClient) -> tuple[str, str, list[dict]]:
    _, owner = await register(client)
    token = invite_token_from_url((await create_invite(client, owner))["url"])
    _, recruiter = await register(client, invite_token=token)
    members = (await client.get("/api/organization/members", headers=bearer(owner))).json()
    return owner, recruiter, members


async def test_owner_sees_members_and_recruiter_does_not(client: AsyncClient) -> None:
    _, recruiter, members = await _org_with_recruiter(client)
    assert {m["role"] for m in members} == {"owner", "recruiter"}
    assert (
        await client.get("/api/organization/members", headers=bearer(recruiter))
    ).status_code == 403


async def test_role_change_bumps_token_version(client: AsyncClient) -> None:
    owner, recruiter, members = await _org_with_recruiter(client)
    recruiter_membership = next(m for m in members if m["role"] == "recruiter")
    response = await client.patch(
        f"/api/organization/members/{recruiter_membership['id']}",
        json={"role": "hiring_manager", "vacancy_scope": ["v-1"]},
        headers=bearer(owner),
    )
    assert response.status_code == 200
    assert response.json()["role"] == "hiring_manager"
    assert response.json()["vacancy_scope"] == ["v-1"]
    # Старая сессия рекрутера больше не действует — права поменялись.
    assert (await client.get("/api/auth/me", headers=bearer(recruiter))).status_code == 401


async def test_vacancy_scope_only_for_hiring_manager(client: AsyncClient) -> None:
    owner, _, members = await _org_with_recruiter(client)
    recruiter_membership = next(m for m in members if m["role"] == "recruiter")
    response = await client.patch(
        f"/api/organization/members/{recruiter_membership['id']}",
        json={"vacancy_scope": ["v-1"]},
        headers=bearer(owner),
    )
    assert response.status_code == 422


async def test_deactivate_and_reactivate_member(client: AsyncClient) -> None:
    owner, recruiter, members = await _org_with_recruiter(client)
    recruiter_membership = next(m for m in members if m["role"] == "recruiter")
    off = await client.post(
        f"/api/organization/members/{recruiter_membership['id']}/deactivate", headers=bearer(owner)
    )
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert (await client.get("/api/auth/me", headers=bearer(recruiter))).status_code == 401

    on = await client.post(
        f"/api/organization/members/{recruiter_membership['id']}/reactivate", headers=bearer(owner)
    )
    assert on.status_code == 200 and on.json()["is_active"] is True
    audit = (await client.get("/api/organization/audit", headers=bearer(owner))).json()
    assert [entry["action"] for entry in audit][:2] == ["member.reactivated", "member.deactivated"]


async def test_last_owner_is_protected(client: AsyncClient) -> None:
    owner, _, members = await _org_with_recruiter(client)
    owner_membership = next(m for m in members if m["role"] == "owner")
    demote = await client.patch(
        f"/api/organization/members/{owner_membership['id']}",
        json={"role": "recruiter"},
        headers=bearer(owner),
    )
    assert demote.status_code == 409
    self_off = await client.post(
        f"/api/organization/members/{owner_membership['id']}/deactivate", headers=bearer(owner)
    )
    assert self_off.status_code == 409


async def test_organization_update_and_audit(client: AsyncClient) -> None:
    _, owner = await register(client, organization_name="Старое имя")
    response = await client.patch(
        "/api/organization", json={"name": "Новое имя", "retention_days": 90}, headers=bearer(owner)
    )
    assert response.status_code == 200
    assert response.json() == {**response.json(), "name": "Новое имя", "retention_days": 90}
    audit = (await client.get("/api/organization/audit", headers=bearer(owner))).json()
    assert audit[0]["action"] == "organization.updated"
    assert audit[0]["details"]["name"]["to"] == "Новое имя"


async def test_member_of_other_org_is_not_found(client: AsyncClient) -> None:
    _, _, members = await _org_with_recruiter(client)
    _, stranger = await register(client, organization_name="Чужая")
    target = next(m for m in members if m["role"] == "recruiter")
    response = await client.post(
        f"/api/organization/members/{target['id']}/deactivate", headers=bearer(stranger)
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("role", "scope", "action", "vacancy_id", "expected"),
    [
        ("owner", None, "org.members", None, True),
        ("recruiter", None, "org.members", None, False),
        ("recruiter", None, "vacancy.write", "v1", True),
        ("hiring_manager", None, "vacancy.write", "v1", False),
        ("hiring_manager", None, "report.read", "v1", True),
        ("hiring_manager", ["v1"], "report.read", "v1", True),
        ("hiring_manager", ["v1"], "report.read", "v2", False),
        ("hiring_manager", ["v1"], "report.decide", "v1", True),
        ("hiring_manager", ["v1"], "assistant.use", None, True),
        ("hiring_manager", [], "report.read", "v1", False),
    ],
)
def test_authorization_matrix(role, scope, action, vacancy_id, expected) -> None:
    from types import SimpleNamespace

    from leonit.accounts.models import MembershipRole

    actor = Actor(
        user=SimpleNamespace(id="u"),  # type: ignore[arg-type]
        membership=SimpleNamespace(role=MembershipRole(role), vacancy_scope=scope),  # type: ignore[arg-type]
        organization=SimpleNamespace(id="o"),  # type: ignore[arg-type]
    )
    assert can(actor, action, vacancy_id=vacancy_id) is expected


def test_migrations_apply_on_fresh_database(tmp_path: Path) -> None:
    """Миграции должны собирать схему с нуля — и совпадать с моделями."""
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "migrations.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    check = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert check.returncode == 0, check.stdout + check.stderr
