from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from leonit.api_tokens.deps import api_auth_failure_limiter, api_rate_limiter
from leonit.api_tokens.models import ApiToken
from leonit.api_tokens.scopes import SCOPES, actions_for
from leonit.core.config import get_settings
from leonit.core.db import get_session_maker
from leonit.core.time import utcnow
from leonit.evaluation.jobs import process_interview
from leonit.main import create_app
from leonit.public_api.docs import SCALAR_CDN_URL, SCALAR_SRI, SCALAR_VERSION
from tests.helpers import bearer, create_invite, invite_token_from_url, register
from tests.test_candidates import _published_vacancy
from tests.test_evaluation import _completed_interview as _rubric_interview
from tests.test_evaluation import _ctx, _finish_answers
from tests.test_reports import _completed_interview

ALL_SCOPES = list(SCOPES)


async def _token(client: AsyncClient, owner: str, scopes: list[str] | None = None, **extra) -> dict:
    response = await client.post(
        "/api/organization/api-tokens",
        json={"name": "Huntflow", "scopes": scopes or ALL_SCOPES, **extra},
        headers=bearer(owner),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------ управление токенами


async def test_owner_creates_token_shown_once_and_stored_hashed(client: AsyncClient) -> None:
    _, owner = await register(client)
    created = await _token(client, owner, ["vacancies:read", "candidates:write"])
    assert created["token"].startswith("leonit_")
    assert created["token_prefix"] == created["token"][:12]
    assert created["status"] == "active" and created["expires_at"] is None
    assert created["scopes"] == ["vacancies:read", "candidates:write"]

    listed = (await client.get("/api/organization/api-tokens", headers=bearer(owner))).json()
    assert [t["id"] for t in listed] == [created["id"]]
    assert "token" not in listed[0]
    assert listed[0]["token_prefix"] == created["token_prefix"]

    async with get_session_maker()() as session:
        row = await session.get(ApiToken, uuid.UUID(created["id"]))
        assert row is not None
        assert row.token_hash == hashlib.sha256(created["token"].encode()).hexdigest()
        assert created["token"] not in (row.token_prefix, row.token_hash)

    audit = (await client.get("/api/organization/audit", headers=bearer(owner))).json()
    assert any(entry["action"] == "api_token.created" for entry in audit)


async def test_token_requires_name_and_known_scopes(client: AsyncClient) -> None:
    _, owner = await register(client)
    for payload in (
        {"name": "  ", "scopes": ["vacancies:read"]},
        {"name": "x", "scopes": []},
        {"name": "x", "scopes": ["admin:everything"]},
    ):
        response = await client.post(
            "/api/organization/api-tokens", json=payload, headers=bearer(owner)
        )
        assert response.status_code == 422, payload


async def test_only_owner_manages_tokens(client: AsyncClient) -> None:
    _, owner = await register(client)
    recruiter_invite = await create_invite(client, owner, role="recruiter")
    _, recruiter = await register(
        client, invite_token=invite_token_from_url(recruiter_invite["url"])
    )
    manager_invite = await create_invite(client, owner, role="hiring_manager")
    _, manager = await register(client, invite_token=invite_token_from_url(manager_invite["url"]))
    # Рекрутер сам умеет писать вакансии, но выпуск токенов — прерогатива владельца:
    # токен переживает увольнение сотрудника, и решать о нём должен владелец.
    for session_token in (recruiter, manager):
        response = await client.post(
            "/api/organization/api-tokens",
            json={"name": "x", "scopes": ["vacancies:write"]},
            headers=bearer(session_token),
        )
        assert response.status_code == 403
        listed = await client.get("/api/organization/api-tokens", headers=bearer(session_token))
        assert listed.status_code == 403


def test_token_actions_follow_scopes_exactly() -> None:
    assert actions_for(["vacancies:read"]) == {"vacancy.read"}
    assert "candidate.read" not in actions_for(["vacancies:read", "reports:read"])
    assert {"candidate.write", "interview.read"} <= actions_for(["candidates:write"])
    # media:read — модификатор отчёта, а не самостоятельный доступ.
    assert actions_for(["media:read"]) == frozenset()
    assert actions_for([]) == frozenset()


# ------------------------------------------------------------- запросы с токеном


async def test_public_api_with_token(client: AsyncClient) -> None:
    _, owner = await register(client, organization_name="Napoleon IT")
    vacancy = await _published_vacancy(client, owner)
    draft = (
        await client.post("/api/vacancies", json={"title": "Черновик"}, headers=bearer(owner))
    ).json()
    api = bearer((await _token(client, owner))["token"])

    listed = await client.get("/api/v1/vacancies", headers=api)
    assert listed.status_code == 200, listed.text
    assert {v["id"] for v in listed.json()} == {vacancy["id"], draft["id"]}
    published = (await client.get("/api/v1/vacancies?status=published", headers=api)).json()
    assert [v["id"] for v in published] == [vacancy["id"]]
    detail = (await client.get(f"/api/v1/vacancies/{vacancy['id']}", headers=api)).json()
    assert detail["question_count"] == 2 and len(detail["questions"]) == 2
    assert detail["settings"]["invitation_days"] == 7

    created = await client.post(
        "/api/v1/vacancies", json={"title": "Из API", "skills": ["Go"]}, headers=api
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft" and created.json()["skills"] == ["Go"]

    candidate = await client.post(
        "/api/v1/candidates",
        json={"full_name": "Анна Иванова", "email": "Anna@Example.com", "external_ref": "hf-42"},
        headers=api,
    )
    assert candidate.status_code == 201, candidate.text
    assert candidate.json()["source"] == "api"
    assert candidate.json()["external_ref"] == "hf-42"
    assert candidate.json()["email"] == "anna@example.com"
    duplicate = await client.post(
        "/api/v1/candidates", json={"full_name": "Анна", "email": "anna@example.com"}, headers=api
    )
    assert duplicate.status_code == 409
    found = (await client.get("/api/v1/candidates?search=анна", headers=api)).json()
    assert [c["email"] for c in found] == ["anna@example.com"]

    invited = await client.post(
        "/api/v1/interviews",
        json={"vacancy_id": vacancy["id"], "full_name": "Пётр Петров", "email": "petr@example.com"},
        headers=api,
    )
    assert invited.status_code == 201, invited.text
    body = invited.json()
    assert body["link"].startswith("http") and "/i/" in body["link"]
    assert body["status"] == "invited"
    assert body["fit_score"] is None and body["recommendation"] is None
    assert body["vacancy_title"] == "Python-разработчик"

    interviews = (
        await client.get(f"/api/v1/interviews?vacancy_id={vacancy['id']}", headers=api)
    ).json()
    assert [i["id"] for i in interviews] == [body["id"]]
    assert interviews[0]["link"] is None
    single = (await client.get(f"/api/v1/interviews/{body['id']}", headers=api)).json()
    assert single["link"] is None and single["candidate_email"] == "petr@example.com"

    again = await client.post(
        "/api/v1/interviews",
        json={"vacancy_id": vacancy["id"], "full_name": "Пётр", "email": "petr@example.com"},
        headers=api,
    )
    assert again.status_code == 409
    to_draft = await client.post(
        "/api/v1/interviews",
        json={"vacancy_id": draft["id"], "full_name": "Пётр", "email": "p2@example.com"},
        headers=api,
    )
    assert to_draft.status_code == 422

    # Созданное через API видно в кабинете как обычные записи с источником api.
    cabinet = (await client.get("/api/candidates", headers=bearer(owner))).json()
    by_email = {c["email"]: c for c in cabinet}
    assert set(by_email) == {"anna@example.com", "petr@example.com"}
    assert by_email["petr@example.com"]["source"] == "api"


async def test_scopes_gate_endpoints(client: AsyncClient) -> None:
    _, owner = await register(client)
    api = bearer((await _token(client, owner, ["vacancies:read"]))["token"])
    assert (await client.get("/api/v1/vacancies", headers=api)).status_code == 200
    forbidden = await client.get("/api/v1/candidates", headers=api)
    assert forbidden.status_code == 403
    assert "candidates:read" in forbidden.json()["detail"]
    assert (
        await client.post("/api/v1/vacancies", json={"title": "x"}, headers=api)
    ).status_code == 403
    assert (await client.get("/api/v1/interviews", headers=api)).status_code == 403


async def test_report_media_links_require_media_scope(client: AsyncClient) -> None:
    owner, interview, _ = await _completed_interview(client)
    url = f"/api/v1/interviews/{interview['id']}/report"

    without_media = bearer((await _token(client, owner, ["reports:read"]))["token"])
    report = await client.get(url, headers=without_media)
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["media_urls_included"] is False
    assert len(data["answers"]) == 2
    assert all(a["media_url"] is None for a in data["answers"])
    assert data["answers"][0]["question_text"] == "Расскажите о себе"
    assert data["interview"]["status"] == "completed"
    assert data["evaluation"] is None  # заключения по интервью ещё нет

    with_media = bearer((await _token(client, owner, ["reports:read", "media:read"]))["token"])
    data = (await client.get(url, headers=with_media)).json()
    assert data["media_urls_included"] is True
    assert all(a["media_url"].startswith("/api/media/") for a in data["answers"])
    # Ссылка подписана и действительно открывает файл.
    media = await client.get(data["answers"][0]["media_url"])
    assert media.status_code == 200

    # media:read без reports:read отчёт не открывает.
    media_only = bearer((await _token(client, owner, ["media:read"]))["token"])
    assert (await client.get(url, headers=media_only)).status_code == 403

    ranking = await client.get(
        f"/api/v1/vacancies/{interview['vacancy_id']}/ranking", headers=without_media
    )
    assert ranking.status_code == 200, ranking.text
    rows = ranking.json()
    assert [r["position"] for r in rows] == [1]
    assert rows[0]["interview_id"] == interview["id"]
    assert rows[0]["candidate_name"] == "Иван Кандидат"
    assert rows[0]["completed_at"] is not None


async def test_revoked_expired_and_unknown_tokens_are_401(client: AsyncClient) -> None:
    owner_email, owner = await register(client)
    created = await _token(client, owner, ["vacancies:read"])
    revoked = await client.delete(
        f"/api/organization/api-tokens/{created['id']}", headers=bearer(owner)
    )
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    # Ответ на отзыв — та же карточка, что в списке: автор токена на месте.
    assert revoked.json()["created_by_email"] == owner_email
    denied = await client.get("/api/v1/vacancies", headers=bearer(created["token"]))
    assert denied.status_code == 401

    expiring = await _token(client, owner, ["vacancies:read"], expires_in_days=1)
    assert expiring["expires_at"] is not None
    assert (
        await client.get("/api/v1/vacancies", headers=bearer(expiring["token"]))
    ).status_code == 200
    async with get_session_maker()() as session:
        await session.execute(
            update(ApiToken)
            .where(ApiToken.id == uuid.UUID(expiring["id"]))
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
        await session.commit()
    assert (
        await client.get("/api/v1/vacancies", headers=bearer(expiring["token"]))
    ).status_code == 401
    listed = (await client.get("/api/organization/api-tokens", headers=bearer(owner))).json()
    statuses = {t["id"]: t["status"] for t in listed}
    assert statuses[created["id"]] == "revoked" and statuses[expiring["id"]] == "expired"

    assert (await client.get("/api/v1/vacancies")).status_code == 401
    assert (
        await client.get("/api/v1/vacancies", headers=bearer("leonit_" + "x" * 43))
    ).status_code == 401
    # Сессионный JWT сотрудника публичный API не принимает.
    assert (await client.get("/api/v1/vacancies", headers=bearer(owner))).status_code == 401


async def test_last_used_at_updates_at_most_once_a_minute(client: AsyncClient) -> None:
    _, owner = await register(client)
    created = await _token(client, owner, ["vacancies:read"])
    assert created["last_used_at"] is None
    await client.get("/api/v1/vacancies", headers=bearer(created["token"]))
    listed = (await client.get("/api/organization/api-tokens", headers=bearer(owner))).json()
    first = listed[0]["last_used_at"]
    assert first is not None
    await client.get("/api/v1/vacancies", headers=bearer(created["token"]))
    listed = (await client.get("/api/organization/api-tokens", headers=bearer(owner))).json()
    assert listed[0]["last_used_at"] == first


async def test_other_organization_is_invisible(client: AsyncClient) -> None:
    _, owner_a = await register(client, organization_name="A")
    _, owner_b = await register(client, organization_name="B")
    vacancy_b = await _published_vacancy(client, owner_b, "Чужая")
    api_a = bearer((await _token(client, owner_a))["token"])

    assert (await client.get("/api/v1/vacancies", headers=api_a)).json() == []
    assert (
        await client.get(f"/api/v1/vacancies/{vacancy_b['id']}", headers=api_a)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/vacancies/{vacancy_b['id']}/ranking", headers=api_a)
    ).status_code == 404
    invite = await client.post(
        "/api/v1/interviews",
        json={"vacancy_id": vacancy_b["id"], "full_name": "Х", "email": "x@example.com"},
        headers=api_a,
    )
    assert invite.status_code == 404
    assert (await client.get("/api/v1/candidates", headers=api_a)).json() == []

    token_b = await _token(client, owner_b, ["vacancies:read"])
    assert (
        await client.delete(
            f"/api/organization/api-tokens/{token_b['id']}", headers=bearer(owner_a)
        )
    ).status_code == 404


async def test_rate_limit_is_per_token(client: AsyncClient, monkeypatch) -> None:
    _, owner = await register(client)
    api = bearer((await _token(client, owner, ["vacancies:read"]))["token"])
    other = bearer((await _token(client, owner, ["vacancies:read"]))["token"])
    monkeypatch.setattr(api_rate_limiter, "max_attempts", 3)
    for _ in range(3):
        assert (await client.get("/api/v1/vacancies", headers=api)).status_code == 200
    limited = await client.get("/api/v1/vacancies", headers=api)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    # Лимит — на токен: соседний токен той же организации не задет.
    assert (await client.get("/api/v1/vacancies", headers=other)).status_code == 200


async def test_failed_auth_attempts_are_limited_per_address(
    client: AsyncClient, monkeypatch
) -> None:
    _, owner = await register(client)
    api = bearer((await _token(client, owner, ["vacancies:read"]))["token"])
    monkeypatch.setattr(api_auth_failure_limiter, "max_attempts", 3)
    # Успешные запросы в счётчик неудач не попадают.
    for _ in range(5):
        assert (await client.get("/api/v1/vacancies", headers=api)).status_code == 200
    for digit in "012":
        unknown = bearer("leonit_" + digit * 43)
        assert (await client.get("/api/v1/vacancies", headers=unknown)).status_code == 401
    limited = await client.get("/api/v1/vacancies", headers=bearer("leonit_" + "z" * 43))
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    # Адрес блокируется до поиска токена в базе — настоящий токен с него тоже ждёт.
    assert (await client.get("/api/v1/vacancies", headers=api)).status_code == 429
    api_auth_failure_limiter.clear()
    assert (await client.get("/api/v1/vacancies", headers=api)).status_code == 200


# --------------------------------------------------------------------- оценка


async def test_evaluated_interview_exposes_scores_and_ranking(client: AsyncClient) -> None:
    owner, interview, vacancy, _ = await _rubric_interview(client)
    api = bearer(
        (await _token(client, owner, ["interviews:read", "reports:read", "candidates:write"]))[
            "token"
        ]
    )
    url = f"/api/v1/interviews/{interview['id']}"
    before = (await client.get(url, headers=api)).json()
    assert before["status"] == "completed"
    assert before["fit_score"] is None and before["recommendation"] is None

    # Медиа-пайплайн проставил транскрипты → задача оценки отработала целиком.
    await _finish_answers(interview["id"])
    result = await process_interview({"interview_id": interview["id"]}, _ctx())
    assert result["status"] == "done" and result["fit_score"] is not None

    single = (await client.get(url, headers=api)).json()
    assert single["status"] == "evaluated" and single["evaluated_at"] is not None
    assert single["fit_score"] == result["fit_score"]
    assert single["recommendation"] == result["recommendation"]

    report = (await client.get(f"{url}/report", headers=api)).json()
    assert report["interview"]["fit_score"] == result["fit_score"]
    assert report["evaluation"]["status"] == "done"
    assert report["evaluation"]["fit_score"] == result["fit_score"]
    assert report["evaluation"]["recommendation"] == result["recommendation"]
    assert report["evaluation"]["output"]["summary"]

    # Ранжирование — то же, что в кабинете (evaluation.service.ranking): оценённые
    # по баллу, ещё не оценённые (в том числе только приглашённые) — в конце.
    invited = await client.post(
        "/api/v1/interviews",
        json={"vacancy_id": vacancy["id"], "full_name": "Ольга", "email": "olga@example.com"},
        headers=api,
    )
    assert invited.status_code == 201, invited.text
    ranking_url = f"/api/v1/vacancies/{vacancy['id']}/ranking"
    rows = (await client.get(ranking_url, headers=api)).json()
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[0]["interview_id"] == interview["id"]
    assert rows[0]["fit_score"] == result["fit_score"]
    assert rows[0]["recommendation"] == result["recommendation"]
    assert rows[0]["evaluated_at"] is not None
    assert rows[1]["interview_id"] == invited.json()["id"] and rows[1]["fit_score"] is None
    cabinet = (
        await client.get(f"/api/vacancies/{vacancy['id']}/ranking", headers=bearer(owner))
    ).json()
    assert [r["interview_id"] for r in cabinet] == [r["interview_id"] for r in rows]


# ---------------------------------------------------------------- документация


async def test_scalar_page_and_openapi_security(client: AsyncClient) -> None:
    page = await client.get("/api/docs/api")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    # Версия бандла зафиксирована, тег несёт SRI и crossorigin.
    assert re.fullmatch(r"\d+\.\d+\.\d+", SCALAR_VERSION)
    assert (
        "https://cdn.jsdelivr.net/npm/@scalar/api-reference"
        f"@{SCALAR_VERSION}/dist/browser/standalone.js"
    ) == SCALAR_CDN_URL
    assert re.fullmatch(r"sha384-[A-Za-z0-9+/]{64}", SCALAR_SRI)
    assert (
        f'<script src="{SCALAR_CDN_URL}" integrity="{SCALAR_SRI}" crossorigin="anonymous">'
        in page.text
    )
    assert "/api/openapi.json" in page.text
    # CSP: скрипты — только CDN и наш инлайн по хешу, без 'unsafe-inline' в script-src.
    csp = page.headers["content-security-policy"]
    directives = dict(directive.split(" ", 1) for directive in csp.split("; "))
    assert directives["default-src"] == "'none'"
    assert directives["connect-src"] == "'self'"
    assert directives["style-src"] == "'self' 'unsafe-inline'"
    assert directives["img-src"] == "data: https:"
    assert directives["font-src"] == "https: data:"
    assert directives["frame-ancestors"] == "'none'"
    inline = re.search(r"<script>(.*?)</script>", page.text, re.S).group(1)  # type: ignore[union-attr]
    digest = base64.b64encode(hashlib.sha256(inline.encode("utf-8")).digest()).decode()
    assert directives["script-src"] == f"https://cdn.jsdelivr.net 'sha256-{digest}'"
    # Запросы «попробовать» уходят на этот же сервер, а не через прокси Scalar.
    assert "proxyUrl: ''" in inline

    spec = (await client.get("/api/openapi.json")).json()
    scheme = spec["components"]["securitySchemes"]["ApiToken"]
    assert scheme["type"] == "http" and scheme["scheme"] == "bearer"
    assert "Аутентификация" in spec["info"]["description"]
    v1_paths = [path for path in spec["paths"] if path.startswith("/api/v1/")]
    assert "/api/v1/interviews/{interview_id}/report" in v1_paths
    assert "/api/v1/vacancies/{vacancy_id}/ranking" in v1_paths
    for path in v1_paths:
        for operation in spec["paths"][path].values():
            assert {"ApiToken": []} in operation["security"], path
            assert operation["description"]
    assert "/api/docs/api" not in spec["paths"]
    # В описаниях и примерах нет ничего похожего на настоящий токен.
    assert not re.search(r"leonit_[A-Za-z0-9_-]{20,}", json.dumps(spec, ensure_ascii=False))


async def test_docs_page_can_be_disabled() -> None:
    app = create_app()
    disabled = get_settings().model_copy(update={"PUBLIC_API_DOCS_ENABLED": False})
    app.dependency_overrides[get_settings] = lambda: disabled
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/api/docs/api")).status_code == 404
        assert (await http.get("/api/openapi.json")).status_code == 200


async def test_docs_page_works_in_production_without_swagger(monkeypatch) -> None:
    production = get_settings().model_copy(
        update={"ENVIRONMENT": "production", "PUBLIC_URL": "https://leonit.example"}
    )
    monkeypatch.setattr("leonit.main.get_settings", lambda: production)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: production
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/api/docs")).status_code == 404
        assert (await http.get("/api/docs/api")).status_code == 200
        spec = (await http.get("/api/openapi.json")).json()
        assert spec["servers"][0]["url"] == "https://leonit.example"
