from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

import leonit.huntflow.jobs  # noqa: F401 — регистрирует huntflow.push
from leonit.core.config import Settings
from leonit.core.crypto import get_secret_box
from leonit.core.db import get_session_maker
from leonit.core.errors import ValidationFailedError
from leonit.huntflow.client import (
    FAKE_ACCOUNT,
    ApplicantCreate,
    HuntflowAuthError,
    HuntflowError,
    HuntflowUnavailableError,
    RealHuntflowClient,
    fake_store,
    reset_fake_stores,
    split_full_name,
)
from leonit.huntflow.models import (
    HuntflowApplicant,
    HuntflowConnection,
    HuntflowConnectionStatus,
    HuntflowMode,
    HuntflowPushStatus,
)
from leonit.huntflow.service import PUSH_JOB, HuntflowService, resolve_mode
from leonit.jobs.models import Job, JobStatus
from leonit.jobs.worker import Worker
from tests.helpers import bearer, create_invite, invite_token_from_url, register
from tests.test_candidates import _published_vacancy
from tests.test_reports import _completed_interview

BASE = "https://huntflow.test/v2"


@pytest.fixture(autouse=True)
def _fresh_fake_store() -> Iterator[None]:
    reset_fake_stores()
    yield
    reset_fake_stores()


def _mock_real_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Подменить реальный клиент сервиса на клиент с MockTransport (без сети)."""

    def factory(self: HuntflowService, token: str) -> RealHuntflowClient:
        return RealHuntflowClient(
            token,
            base_url=BASE,
            timeout_s=5,
            transport=httpx.MockTransport(handler),
            retry_delay_s=0,
        )

    monkeypatch.setattr(HuntflowService, "_real_client", factory)


async def _run_push_jobs() -> None:
    worker = Worker(worker_id="w-huntflow", poll_interval=0.01, heartbeat_s=0.05, kinds=[PUSH_JOB])
    while await worker.run_once():
        pass


async def _connect_demo(client: AsyncClient, token: str) -> dict:
    response = await client.post(
        "/api/integrations/huntflow/connect", json={"demo": True}, headers=bearer(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _link(
    client: AsyncClient, token: str, vacancy_id: str, huntflow_vacancy_id: int = 101, status_id=3
) -> dict:
    response = await client.put(
        f"/api/integrations/huntflow/links/{vacancy_id}",
        json={"huntflow_vacancy_id": huntflow_vacancy_id, "status_id": status_id},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _connection_row(email_token_owner: str | None = None) -> HuntflowConnection | None:
    async with get_session_maker()() as session:
        rows = list(await session.scalars(select(HuntflowConnection)))
        return rows[-1] if rows else None


# --- подключение --------------------------------------------------------------


async def test_connect_demo_status_vacancies_and_disconnect(client: AsyncClient) -> None:
    _, token = await register(client)
    empty = (await client.get("/api/integrations/huntflow", headers=bearer(token))).json()
    assert empty["connected"] is False and empty["demo_available"] is True
    assert empty["can_manage"] is True

    connected = await _connect_demo(client, token)
    assert connected["connected"] is True
    assert connected["mode"] == "fake" and connected["status"] == "active"
    assert connected["account"] == {"id": FAKE_ACCOUNT.id, "name": FAKE_ACCOUNT.name, "nick": None}
    assert connected["owner_email"] == "demo@huntflow.local"

    vacancies = await client.get("/api/integrations/huntflow/vacancies", headers=bearer(token))
    assert vacancies.status_code == 200, vacancies.text
    body = vacancies.json()
    assert [v["position"] for v in body["items"]] == [
        "Python-разработчик",
        "Frontend-разработчик (React)",
        "Аналитик данных",
    ]
    assert [s["name"] for s in body["statuses"]][:2] == ["Новый", "Скрининг"]
    assert all(v["links"] == [] for v in body["items"])

    # Демо-подключение не хранит токен.
    row = await _connection_row()
    assert row is not None and row.token_encrypted is None and row.mode == HuntflowMode.fake

    gone = await client.delete("/api/integrations/huntflow", headers=bearer(token))
    assert gone.status_code == 204
    after = (await client.get("/api/integrations/huntflow", headers=bearer(token))).json()
    assert after["connected"] is False
    assert (
        await client.get("/api/integrations/huntflow/vacancies", headers=bearer(token))
    ).status_code == 409


async def test_connect_requires_token_or_demo(client: AsyncClient) -> None:
    _, token = await register(client)
    response = await client.post(
        "/api/integrations/huntflow/connect", json={"token": "   "}, headers=bearer(token)
    )
    assert response.status_code == 422


async def test_invalid_token_marks_connection_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": [{"detail": "Unauthorized"}]})

    _mock_real_client(monkeypatch, handler)
    _, token = await register(client)
    response = await client.post(
        "/api/integrations/huntflow/connect", json={"token": "bad-token"}, headers=bearer(token)
    )
    assert response.status_code == 422, response.text
    assert "отклонил" in response.json()["detail"]

    status = (await client.get("/api/integrations/huntflow", headers=bearer(token))).json()
    assert status["connected"] is True and status["status"] == "error"
    assert status["mode"] == "real" and "отклонил" in status["last_error"]
    # Пока подключение в ошибке, вакансии не запрашиваются.
    assert (
        await client.get("/api/integrations/huntflow/vacancies", headers=bearer(token))
    ).status_code == 409


async def test_token_is_encrypted_and_account_is_selected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": 5, "name": "Рекрутер", "email": "r@corp.ru"})
        if request.url.path.endswith("/accounts"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 10, "name": "Корпорация", "nick": "corp"},
                        {"id": 11, "name": "Дочка", "nick": "sub"},
                    ]
                },
            )
        return httpx.Response(404, json={})

    _mock_real_client(monkeypatch, handler)
    _, token = await register(client)
    response = await client.post(
        "/api/integrations/huntflow/connect",
        json={"token": "personal-secret-token"},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "needs_account" and body["account"] is None
    assert [a["id"] for a in body["available_accounts"]] == [10, 11]
    assert body["owner_name"] == "Рекрутер"
    assert all(value == "Bearer personal-secret-token" for value in seen_auth)

    row = await _connection_row()
    assert row is not None and row.mode == HuntflowMode.real
    assert row.token_encrypted and "personal-secret-token" not in row.token_encrypted
    assert get_secret_box().decrypt(row.token_encrypted) == "personal-secret-token"

    wrong = await client.post(
        "/api/integrations/huntflow/account", json={"account_id": 99}, headers=bearer(token)
    )
    assert wrong.status_code == 422
    chosen = await client.post(
        "/api/integrations/huntflow/account", json={"account_id": 11}, headers=bearer(token)
    )
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["status"] == "active"
    assert chosen.json()["account"] == {"id": 11, "name": "Дочка", "nick": None}


def test_resolve_mode_follows_settings() -> None:
    auto = Settings(HUNTFLOW_MODE="auto")
    assert resolve_mode(auto, demo=True) == HuntflowMode.fake
    assert resolve_mode(auto, demo=False) == HuntflowMode.real
    assert resolve_mode(Settings(HUNTFLOW_MODE="fake"), demo=False) == HuntflowMode.fake
    assert resolve_mode(Settings(HUNTFLOW_MODE="real"), demo=False) == HuntflowMode.real
    with pytest.raises(ValidationFailedError):
        resolve_mode(Settings(HUNTFLOW_MODE="real"), demo=True)


# --- привязка и импорт --------------------------------------------------------


async def test_link_vacancy_and_import_applicants_without_duplicates(client: AsyncClient) -> None:
    _, token = await register(client)
    await _connect_demo(client, token)
    vacancy = await _published_vacancy(client, token)

    unknown = await client.put(
        f"/api/integrations/huntflow/links/{vacancy['id']}",
        json={"huntflow_vacancy_id": 999},
        headers=bearer(token),
    )
    assert unknown.status_code == 422
    not_linked = await client.post(
        f"/api/integrations/huntflow/links/{vacancy['id']}/import", headers=bearer(token)
    )
    assert not_linked.status_code == 409

    link = await _link(client, token, vacancy["id"])
    assert link["huntflow_vacancy_title"] == "Python-разработчик"
    assert link["status_name"] == "Видеоинтервью LeonIT"
    listed = (
        await client.get("/api/integrations/huntflow/vacancies", headers=bearer(token))
    ).json()
    python = next(v for v in listed["items"] if v["id"] == 101)
    assert python["links"][0]["vacancy_id"] == vacancy["id"]
    status = (await client.get("/api/integrations/huntflow", headers=bearer(token))).json()
    assert status["linked_vacancies"] == 1

    imported = await client.post(
        f"/api/integrations/huntflow/links/{vacancy['id']}/import", headers=bearer(token)
    )
    assert imported.status_code == 200, imported.text
    assert imported.json() == {"total": 3, "created": 2, "existing": 0, "skipped": 1}

    candidates = (await client.get("/api/candidates", headers=bearer(token))).json()
    by_email = {c["email"]: c for c in candidates}
    assert set(by_email) == {"maria.smirnova@example.com", "a.kuznetsov@example.com"}
    assert by_email["a.kuznetsov@example.com"]["full_name"] == "Кузнецов Алексей Игоревич"
    assert by_email["a.kuznetsov@example.com"]["source"] == "huntflow"
    assert by_email["maria.smirnova@example.com"]["external_ref"] == "huntflow:1001"
    assert by_email["maria.smirnova@example.com"]["phone"] == "+7 900 000-00-01"

    again = await client.post(
        f"/api/integrations/huntflow/links/{vacancy['id']}/import", headers=bearer(token)
    )
    assert again.json() == {"total": 3, "created": 0, "existing": 2, "skipped": 1}
    assert len((await client.get("/api/candidates", headers=bearer(token))).json()) == 2

    links = (await client.get("/api/integrations/huntflow/links", headers=bearer(token))).json()
    assert links[0]["last_imported_at"] is not None

    unlinked = await client.delete(
        f"/api/integrations/huntflow/links/{vacancy['id']}", headers=bearer(token)
    )
    assert unlinked.status_code == 204
    assert (
        await client.get("/api/integrations/huntflow/links", headers=bearer(token))
    ).json() == []


# --- передача кандидата -------------------------------------------------------


async def test_push_candidate_creates_applicant_link_and_report_share(client: AsyncClient) -> None:
    token, interview, _ = await _completed_interview(client)
    await _connect_demo(client, token)
    await _link(client, token, interview["vacancy_id"])
    candidate_id = interview["candidate_id"]

    before = (
        await client.get(
            f"/api/integrations/huntflow/candidates/{candidate_id}/push", headers=bearer(token)
        )
    ).json()
    assert before["status"] == "not_pushed"

    accepted = await client.post(
        f"/api/integrations/huntflow/candidates/{candidate_id}/push",
        json={},
        headers=bearer(token),
    )
    assert accepted.status_code == 202, accepted.text
    queued = accepted.json()
    assert queued["status"] == "queued" and queued["job"]["status"] == "queued"
    assert queued["interview_id"] == interview["id"]

    await _run_push_jobs()

    pushed = (
        await client.get(
            f"/api/integrations/huntflow/candidates/{candidate_id}/push", headers=bearer(token)
        )
    ).json()
    assert pushed["status"] == "pushed", pushed
    assert pushed["job"]["status"] == "succeeded"
    assert pushed["huntflow_applicant_id"] == 2001
    assert pushed["huntflow_vacancy_id"] == 101 and pushed["huntflow_status_id"] == 3
    assert pushed["last_pushed_at"] is not None and pushed["last_error"] is None
    assert pushed["report_share_url"] and "/r/" in pushed["report_share_url"]

    # Соискатель создан из карточки кандидата, привязан к вакансии со статусом.
    store = fake_store(str((await _connection_row()).organization_id))  # type: ignore[union-attr]
    applicant = store.applicants[2001]
    assert applicant["email"] == "cand@example.com"
    assert applicant["first_name"] == "Кандидат" and applicant["last_name"] == "Иван"
    assert applicant["position"] == "Python-разработчик"
    assert applicant["links"] == [{"vacancy": 101, "status": 3}]
    log = store.logs[2001]
    assert len(log) == 1
    comment = log[0]["comment"]
    assert comment.startswith("LeonIT: видеоинтервью по вакансии «Python-разработчик»")
    assert pushed["report_share_url"] in comment

    # Ссылка из комментария открывает публичный отчёт.
    share_token = pushed["report_share_url"].rsplit("/r/", 1)[1]
    report = await client.get(f"/api/public/reports/{share_token}")
    assert report.status_code == 200, report.text
    assert report.json()["candidate_name"] == "Иван Кандидат"
    shares = (
        await client.get(f"/api/interviews/{interview['id']}/shares", headers=bearer(token))
    ).json()
    assert len(shares) == 1 and shares[0]["label"] == "Huntflow"

    candidate = (await client.get(f"/api/candidates/{candidate_id}", headers=bearer(token))).json()
    assert candidate["external_ref"] == "huntflow:2001"

    # Повторная передача обновляет привязку и комментарий, соискатель тот же.
    again = await client.post(
        f"/api/integrations/huntflow/candidates/{candidate_id}/push",
        json={"interview_id": interview["id"]},
        headers=bearer(token),
    )
    assert again.status_code == 202
    await _run_push_jobs()
    repeated = (
        await client.get(
            f"/api/integrations/huntflow/candidates/{candidate_id}/push", headers=bearer(token)
        )
    ).json()
    assert repeated["status"] == "pushed"
    assert repeated["huntflow_applicant_id"] == 2001
    assert repeated["report_share_url"] == pushed["report_share_url"]
    assert [a for a in store.applicants.values() if a.get("email") == "cand@example.com"] == [
        applicant
    ]
    assert len(store.logs[2001]) == 2
    assert (
        len(
            (
                await client.get(f"/api/interviews/{interview['id']}/shares", headers=bearer(token))
            ).json()
        )
        == 1
    )

    async with get_session_maker()() as session:
        rows = list(
            await session.scalars(
                select(HuntflowApplicant).where(HuntflowApplicant.huntflow_applicant_id == 2001)
            )
        )
        assert len(rows) == 1 and rows[0].status == HuntflowPushStatus.pushed
        jobs_ = list(await session.scalars(select(Job).where(Job.kind == PUSH_JOB)))
        assert all(j.status == JobStatus.succeeded for j in jobs_)


async def test_push_reuses_existing_applicant_by_email(client: AsyncClient) -> None:
    token, interview, _ = await _completed_interview(client)
    await _connect_demo(client, token)
    await _link(client, token, interview["vacancy_id"], status_id=None)
    store = fake_store(str((await _connection_row()).organization_id))  # type: ignore[union-attr]
    # В Huntflow уже есть соискатель с таким e-mail — второго создавать нельзя.
    store.applicants[1500] = {
        "id": 1500,
        "first_name": "Иван",
        "last_name": "Кандидат",
        "email": "CAND@example.com",
        "links": [],
    }

    accepted = await client.post(
        f"/api/integrations/huntflow/candidates/{interview['candidate_id']}/push",
        json={},
        headers=bearer(token),
    )
    assert accepted.status_code == 202
    await _run_push_jobs()
    pushed = (
        await client.get(
            f"/api/integrations/huntflow/candidates/{interview['candidate_id']}/push",
            headers=bearer(token),
        )
    ).json()
    assert pushed["status"] == "pushed" and pushed["huntflow_applicant_id"] == 1500
    # Статус не задан в привязке — берётся первый статус воронки.
    assert pushed["huntflow_status_id"] == 1
    assert 2001 not in store.applicants


async def test_push_requires_linked_vacancy(client: AsyncClient) -> None:
    token, interview, _ = await _completed_interview(client)
    await _connect_demo(client, token)
    response = await client.post(
        f"/api/integrations/huntflow/candidates/{interview['candidate_id']}/push",
        json={},
        headers=bearer(token),
    )
    assert response.status_code == 422
    assert "привязан" in response.json()["detail"]


async def test_push_failure_is_visible_in_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, interview, _ = await _completed_interview(client)
    await _connect_demo(client, token)
    await _link(client, token, interview["vacancy_id"])

    async def broken(self, account_id, data):
        raise HuntflowError("Huntflow ответил 400: phone is invalid")

    from leonit.huntflow.client import FakeHuntflowClient

    monkeypatch.setattr(FakeHuntflowClient, "create_applicant", broken)
    await client.post(
        f"/api/integrations/huntflow/candidates/{interview['candidate_id']}/push",
        json={},
        headers=bearer(token),
    )
    await _run_push_jobs()
    status = (
        await client.get(
            f"/api/integrations/huntflow/candidates/{interview['candidate_id']}/push",
            headers=bearer(token),
        )
    ).json()
    assert status["status"] == "error"
    assert "phone is invalid" in status["last_error"]
    # Ответ 4xx повтором не лечится — задача завершена, а не поставлена заново.
    assert status["job"]["status"] == "succeeded"


# --- роли ---------------------------------------------------------------------


async def test_roles(client: AsyncClient) -> None:
    _, owner = await register(client)
    await _connect_demo(client, owner)
    vacancy = await _published_vacancy(client, owner)
    recruiter_invite = await create_invite(client, owner, role="recruiter")
    _, recruiter = await register(
        client, invite_token=invite_token_from_url(recruiter_invite["url"])
    )
    manager_invite = await create_invite(
        client, owner, role="hiring_manager", vacancy_scope=[vacancy["id"]]
    )
    _, manager = await register(client, invite_token=invite_token_from_url(manager_invite["url"]))

    # Рекрутер: видит статус и вакансии, привязывает, импортирует, но не управляет подключением.
    status = await client.get("/api/integrations/huntflow", headers=bearer(recruiter))
    assert status.status_code == 200 and status.json()["can_manage"] is False
    assert (
        await client.post(
            "/api/integrations/huntflow/connect", json={"demo": True}, headers=bearer(recruiter)
        )
    ).status_code == 403
    assert (
        await client.delete("/api/integrations/huntflow", headers=bearer(recruiter))
    ).status_code == 403
    assert (
        await client.get("/api/integrations/huntflow/vacancies", headers=bearer(recruiter))
    ).status_code == 200
    await _link(client, recruiter, vacancy["id"])
    imported = await client.post(
        f"/api/integrations/huntflow/links/{vacancy['id']}/import", headers=bearer(recruiter)
    )
    assert imported.status_code == 200
    candidate_id = (await client.get("/api/candidates", headers=bearer(recruiter))).json()[0]["id"]
    # У импортированного кандидата нет интервью — передача невозможна, но право есть.
    assert (
        await client.post(
            f"/api/integrations/huntflow/candidates/{candidate_id}/push",
            json={},
            headers=bearer(recruiter),
        )
    ).status_code == 422

    # Нанимающий менеджер: 403 на всё.
    for method, path, body in (
        ("GET", "/api/integrations/huntflow", None),
        ("POST", "/api/integrations/huntflow/connect", {"demo": True}),
        ("DELETE", "/api/integrations/huntflow", None),
        ("GET", "/api/integrations/huntflow/vacancies", None),
        (
            "PUT",
            f"/api/integrations/huntflow/links/{vacancy['id']}",
            {"huntflow_vacancy_id": 101},
        ),
        ("POST", f"/api/integrations/huntflow/links/{vacancy['id']}/import", None),
        ("POST", f"/api/integrations/huntflow/candidates/{candidate_id}/push", {}),
        ("GET", f"/api/integrations/huntflow/candidates/{candidate_id}/push", None),
    ):
        response = await client.request(method, path, json=body, headers=bearer(manager))
        assert response.status_code == 403, (method, path, response.text)


# --- реальный клиент через MockTransport ----------------------------------------


async def test_real_client_pagination_retry_and_errors() -> None:
    calls: list[str] = []
    me_attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}?{request.url.query.decode()}")
        path = request.url.path
        if path == "/v2/me":
            me_attempts["n"] += 1
            if me_attempts["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, json={"id": 1, "name": "Я", "email": "me@corp.ru"})
        if path == "/v2/accounts/1/vacancies":
            page = int(request.url.params.get("page", "1"))
            items = {
                1: [{"id": 1, "position": "A", "state": "OPEN"}, {"id": 2, "position": "B"}],
                2: [{"id": 3, "position": "C", "company": "Corp"}],
            }[page]
            return httpx.Response(
                200, json={"items": items, "page": page, "total_pages": 2, "total_items": 3}
            )
        if path == "/v2/accounts/1/vacancies/statuses":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": 7, "name": "Второй", "order": 2},
                        {"id": 6, "name": "Первый", "order": 1},
                        {"id": 8, "name": "Удалён", "order": 3, "removed": "2026-01-01"},
                    ]
                },
            )
        if path == "/v2/accounts/1/applicants" and request.method == "GET":
            assert request.url.params.get("vacancy") == "3"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 42,
                            "first_name": "Анна",
                            "last_name": "Иванова",
                            "email": "Anna@Example.com",
                            "links": [{"vacancy": {"id": 3}, "status": {"id": 6}}],
                        }
                    ],
                    "total_pages": 1,
                },
            )
        if path == "/v2/accounts/1/applicants" and request.method == "POST":
            body = json.loads(request.content)
            assert body == {"first_name": "Пётр", "last_name": "Петров", "email": "p@x.ru"}
            return httpx.Response(200, json={"id": 43, **body})
        if path == "/v2/accounts/1/applicants/43/vacancy":
            body = json.loads(request.content)
            assert body == {"vacancy": 3, "status": 6, "comment": "Привет"}
            return httpx.Response(200, json={"id": 900, **body})
        if path == "/v2/accounts/1/applicants/43/logs":
            return httpx.Response(200, json={"items": [{"id": 900, "type": "STATUS"}]})
        if path == "/v2/accounts/1/applicants/404":
            return httpx.Response(404, json={"errors": [{"detail": "not found"}]})
        if path == "/v2/boom":
            return httpx.Response(503)
        if path == "/v2/forbidden":
            return httpx.Response(401)
        return httpx.Response(400, json={"errors": [{"title": "bad"}]})

    async with RealHuntflowClient(
        "tok", base_url=BASE, timeout_s=5, transport=httpx.MockTransport(handler), retry_delay_s=0
    ) as api:
        me = await api.me()
        assert me.email == "me@corp.ru" and me_attempts["n"] == 2  # 429 → один повтор
        vacancies = await api.vacancies(1)
        assert [v.id for v in vacancies] == [1, 2, 3] and vacancies[2].company == "Corp"
        assert sum("vacancies?" in c for c in calls) == 2
        statuses = await api.statuses(1)
        assert [s.name for s in statuses] == ["Первый", "Второй"]
        applicants = await api.applicants(1, vacancy_id=3)
        assert applicants[0].email == "anna@example.com"
        assert applicants[0].full_name == "Иванова Анна"
        assert applicants[0].links[0].vacancy_id == 3 and applicants[0].links[0].status_id == 6
        created = await api.create_applicant(
            1, ApplicantCreate(first_name="Пётр", last_name="Петров", email="p@x.ru")
        )
        assert created.id == 43
        attached = await api.attach_vacancy(1, 43, vacancy_id=3, status_id=6, comment="Привет")
        assert attached["id"] == 900
        assert (await api.applicant_logs(1, 43))[0]["type"] == "STATUS"
        assert await api.get_applicant(1, 404) is None
        with pytest.raises(HuntflowUnavailableError):
            await api._request("GET", "/boom")
        assert calls.count("GET /v2/boom?") == 2  # 503 → один повтор, затем ошибка
        with pytest.raises(HuntflowAuthError):
            await api._request("GET", "/forbidden")
        with pytest.raises(HuntflowError, match="400"):
            await api._request("GET", "/whatever")


async def test_real_client_timeout_becomes_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    async with RealHuntflowClient(
        "tok", base_url=BASE, timeout_s=0.5, transport=httpx.MockTransport(handler), retry_delay_s=0
    ) as api:
        with pytest.raises(HuntflowUnavailableError, match="не ответил"):
            await api.me()


def test_split_full_name() -> None:
    assert split_full_name("Иванов Иван Иванович") == ("Иван", "Иванов", "Иванович")
    assert split_full_name("Иванов Иван") == ("Иван", "Иванов", None)
    assert split_full_name("Иван") == ("Иван", "", None)
    assert split_full_name("  ") == ("", "", None)


async def test_status_of_connection_in_error_after_401_on_vacancies(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"valid": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if not state["valid"]:
            return httpx.Response(401)
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": 1, "name": "Я", "email": "me@corp.ru"})
        if request.url.path.endswith("/accounts"):
            return httpx.Response(200, json={"items": [{"id": 1, "name": "Corp"}]})
        return httpx.Response(200, json={"items": [], "total_pages": 1})

    _mock_real_client(monkeypatch, handler)
    _, token = await register(client)
    connected = await client.post(
        "/api/integrations/huntflow/connect", json={"token": "ok"}, headers=bearer(token)
    )
    assert connected.status_code == 200 and connected.json()["status"] == "active"
    # Токен отозвали на стороне Huntflow: первый же запрос переводит подключение в error.
    state["valid"] = False
    response = await client.get("/api/integrations/huntflow/vacancies", headers=bearer(token))
    assert response.status_code == 502
    status = (await client.get("/api/integrations/huntflow", headers=bearer(token))).json()
    assert status["status"] == "error"
    async with get_session_maker()() as session:
        row = await session.scalar(
            select(HuntflowConnection).order_by(HuntflowConnection.created_at.desc())
        )
        assert row is not None and row.status == HuntflowConnectionStatus.error
