"""Интеграция с HH.ru: fake-режим насквозь, реальный клиент через MockTransport."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import func, select

from leonit.ai.providers.base import LLMProvider, LLMResponse
from leonit.candidates.models import Candidate, Interview, InterviewStatus
from leonit.candidates.service import stored_link_token
from leonit.core.config import Settings, get_settings
from leonit.core.crypto import get_secret_box
from leonit.core.db import get_session_maker
from leonit.core.time import aware, utcnow
from leonit.hh.client import HhAuthError, HhOAuth, RealHhClient
from leonit.hh.dialog import idempotency_key
from leonit.hh.jobs import hh_sync_job
from leonit.hh.models import HhConnection, HhNegotiation
from leonit.hh.oauth import make_pkce, make_state, parse_state
from leonit.hh.service import HH_SYNC_JOB, ensure_periodic_sync, sync_organizations
from leonit.hh.slots import extract_slot, parse_slot_rules
from leonit.hh.types import HhTokens
from leonit.jobs.models import Job, JobStatus
from leonit.jobs.registry import JobContext
from leonit.jobs.worker import Worker
from leonit.notifications.models import EmailMessage
from tests.helpers import bearer, create_invite, invite_token_from_url, register

HH = "/api/integrations/hh"

# ------------------------------------------------------------------ helpers


async def _member(client: AsyncClient, owner_token: str, role: str) -> str:
    invite = await create_invite(client, owner_token, role=role)
    _, token = await register(client, invite_token=invite_token_from_url(invite["url"]))
    return token


async def _connect_demo(client: AsyncClient, token: str) -> dict:
    response = await client.post(f"{HH}/connect-demo", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


async def _import(client: AsyncClient, token: str, hh_vacancy_id: str) -> dict:
    response = await client.post(f"{HH}/vacancies/{hh_vacancy_id}/import", headers=bearer(token))
    assert response.status_code == 201, response.text
    return response.json()


async def _publish(client: AsyncClient, token: str, vacancy_id: str) -> dict:
    await client.put(
        f"/api/vacancies/{vacancy_id}/questions",
        json={"questions": [{"text": "Расскажите о себе"}, {"text": "Что такое GIL?"}]},
        headers=bearer(token),
    )
    response = await client.post(f"/api/vacancies/{vacancy_id}/publish", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


async def _import_published(client: AsyncClient, token: str, hh_vacancy_id: str) -> dict:
    link = await _import(client, token, hh_vacancy_id)
    await _publish(client, token, link["vacancy_id"])
    return link


async def _org_id(token: str, client: AsyncClient) -> uuid.UUID:
    me = await client.get("/api/auth/me", headers=bearer(token))
    return uuid.UUID(me.json()["organization"]["id"])


async def _sync(organization_id: uuid.UUID) -> dict[str, Any]:
    async with get_session_maker()() as session:
        return await sync_organizations(session, organization_id=organization_id)


async def _negotiations(client: AsyncClient, token: str, **params: str) -> dict[str, dict]:
    response = await client.get(f"{HH}/negotiations", params=params, headers=bearer(token))
    assert response.status_code == 200, response.text
    return {item["negotiation_id"]: item for item in response.json()}


def _steps(item: dict) -> list[str | None]:
    return [m.get("step") for m in item["messages"] if m["role"] == "bot"]


def _snapshot(items: dict[str, dict]) -> str:
    """Состояние откликов без времени последней синхронизации (оно меняется всегда)."""
    return json.dumps(
        {
            key: {k: v for k, v in item.items() if k != "last_synced_at"}
            for key, item in items.items()
        },
        sort_keys=True,
    )


async def _run_job(job_id: str) -> Job:
    """Прогнать очередь hh.sync до завершения конкретной задачи."""
    worker = Worker(worker_id="w-hh", kinds=[HH_SYNC_JOB], concurrency={"llm": 1, "default": 1})
    for _ in range(20):
        async with get_session_maker()() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            assert job is not None
            if job.is_terminal:
                return job
        if not await worker.run_once():
            break
    raise AssertionError("задача hh.sync не завершилась")


class ScriptedLLM(LLMProvider):
    role = "assistant"
    model = "scripted"

    def __init__(self, content: str | None = None, *, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls = 0

    async def chat(
        self, messages, *, tools=None, response_format=None, temperature=None, max_tokens=None
    ):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResponse(content=self.content, raw={"provider": "scripted"})

    async def stream_chat(self, messages, *, tools=None, temperature=None, max_tokens=None):
        raise NotImplementedError
        yield  # pragma: no cover


# --------------------------------------------------------- подключение и роли


async def test_demo_connect_status_and_encrypted_tokens(client: AsyncClient) -> None:
    _, token = await register(client)
    before = (await client.get(f"{HH}/status", headers=bearer(token))).json()
    assert before["mode"] == "fake" and before["configured"] is False
    assert before["connection"] is None

    status = await _connect_demo(client, token)
    connection = status["connection"]
    assert connection["status"] == "connected" and connection["mode"] == "fake"
    assert connection["employer_name"].startswith("Napoleon IT")
    assert connection["webhook_url"].startswith(
        f"{get_settings().PUBLIC_URL}/api/integrations/hh/webhook/"
    )

    org = await _org_id(token, client)
    async with get_session_maker()() as session:
        row = await session.scalar(select(HhConnection).where(HhConnection.organization_id == org))
        assert row is not None
        assert "fake-access-token" not in row.access_token_enc
        assert "fake-refresh-token" not in row.refresh_token_enc
        assert get_secret_box().decrypt(row.access_token_enc) == "fake-access-token"
        secret = get_secret_box().decrypt(row.webhook_secret_enc)
        assert connection["webhook_url"].endswith(secret)

    # Повторное подключение переиспользует строку, а не создаёт вторую.
    await _connect_demo(client, token)
    async with get_session_maker()() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(HhConnection)
            .where(HhConnection.organization_id == org)
        )
        assert count == 1

    disconnected = await client.post(f"{HH}/disconnect", headers=bearer(token))
    assert disconnected.status_code == 200 and disconnected.json()["connection"] is None
    assert (await client.get(f"{HH}/vacancies", headers=bearer(token))).status_code == 404


async def test_roles_matrix(client: AsyncClient) -> None:
    _, owner = await register(client)
    recruiter = await _member(client, owner, "recruiter")
    manager = await _member(client, owner, "hiring_manager")

    # Рекрутер не подключает и не отключает.
    assert (await client.post(f"{HH}/connect-demo", headers=bearer(recruiter))).status_code == 403
    assert (await client.post(f"{HH}/oauth/start", headers=bearer(recruiter))).status_code == 403
    await _connect_demo(client, owner)
    assert (await client.post(f"{HH}/disconnect", headers=bearer(recruiter))).status_code == 403

    # Рекрутер синхронизирует, импортирует и настраивает диалог.
    status = (await client.get(f"{HH}/status", headers=bearer(recruiter))).json()
    assert status["connection"]["webhook_url"] is None  # адрес вебхука — только владельцу
    assert (await client.get(f"{HH}/vacancies", headers=bearer(recruiter))).status_code == 200
    link = await _import(client, recruiter, "hh-v-1003")
    dialog = await client.put(
        f"{HH}/links/{link['id']}/dialog",
        json={
            "enabled": True,
            "max_days": 5,
            "greeting": "Привет, {candidate_name}",
            "clarify": "Когда?",
            "link": "{link}",
        },
        headers=bearer(recruiter),
    )
    assert dialog.status_code == 200 and dialog.json()["max_days"] == 5
    assert (await client.post(f"{HH}/sync", headers=bearer(recruiter))).status_code == 202

    # Нанимающий менеджер — 403 везде.
    for method, path in (
        ("GET", f"{HH}/status"),
        ("GET", f"{HH}/vacancies"),
        ("GET", f"{HH}/links"),
        ("GET", f"{HH}/negotiations"),
        ("GET", f"{HH}/links/{link['id']}/dialog"),
        ("POST", f"{HH}/sync"),
        ("POST", f"{HH}/vacancies/hh-v-1001/import"),
        ("POST", f"{HH}/connect-demo"),
    ):
        response = await client.request(method, path, headers=bearer(manager))
        assert response.status_code == 403, (method, path, response.text)


# ------------------------------------------------------------- oauth и вебхук


async def test_oauth_state_is_signed_and_short_lived(client: AsyncClient) -> None:
    settings = get_settings()
    box = get_secret_box()
    org, user = uuid.uuid4(), uuid.uuid4()
    verifier, challenge = make_pkce()
    assert len(challenge) == 43 and "=" not in challenge  # S256, base64url без паддинга
    state = make_state(settings, box, organization_id=org, user_id=user, code_verifier=verifier)
    parsed = parse_state(settings, box, state)
    assert parsed is not None
    assert parsed.organization_id == org and parsed.user_id == user
    assert parsed.code_verifier == verifier and parsed.nonce
    assert verifier not in state  # verifier зашифрован, из адресной строки не читается

    assert parse_state(settings, box, "garbage") is None
    assert parse_state(settings, box, state[:-3] + "abc") is None  # подделанная подпись
    forged = jwt.encode(
        {"typ": "hh_oauth", "org": str(org), "sub": str(user), "cv": "x", "exp": utcnow()},
        "wrong-secret",
        algorithm=settings.JWT_ALGORITHM,
    )
    assert parse_state(settings, box, forged) is None
    expired = jwt.encode(
        {
            "typ": "hh_oauth",
            "org": str(org),
            "sub": str(user),
            "cv": box.encrypt(verifier),
            "nonce": "n",
            "exp": utcnow() - timedelta(minutes=1),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    assert parse_state(settings, box, expired) is None

    # Callback с поддельным state — редирект на страницу с ошибкой, ничего не сохраняется.
    response = await client.get(f"{HH}/callback", params={"code": "abc", "state": "forged"})
    assert response.status_code == 302
    assert response.headers["location"].endswith("/integrations/hh?status=error&reason=state")
    denied = await client.get(f"{HH}/callback", params={"error": "access_denied"})
    assert denied.headers["location"].endswith("reason=denied")

    # В fake-режиме настоящий OAuth недоступен — только демо-аккаунт.
    _, token = await register(client)
    assert (await client.post(f"{HH}/oauth/start", headers=bearer(token))).status_code == 409


async def test_oauth_start_builds_pkce_url_with_keys(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Settings(HH_CLIENT_ID="cid", HH_CLIENT_SECRET="csec", HH_OAUTH_BASE="https://hh.test")
    monkeypatch.setattr("leonit.hh.service.get_settings", lambda: real)
    _, token = await register(client)
    response = await client.post(f"{HH}/oauth/start", headers=bearer(token))
    assert response.status_code == 200, response.text
    url = urlparse(response.json()["url"])
    query = parse_qs(url.query)
    assert url.scheme == "https" and url.netloc == "hh.test" and url.path == "/oauth/authorize"
    assert query["client_id"] == ["cid"] and query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [real.hh_redirect_url]
    parsed = parse_state(real, get_secret_box(), query["state"][0])
    assert parsed is not None and parsed.organization_id == await _org_id(token, client)
    # Демо-подключение при заданных ключах закрыто.
    assert (await client.post(f"{HH}/connect-demo", headers=bearer(token))).status_code == 409


async def test_webhook_secret_and_dedupe(client: AsyncClient) -> None:
    _, token = await register(client)
    status = await _connect_demo(client, token)
    secret = status["connection"]["webhook_url"].rsplit("/", 1)[1]

    assert (await client.post(f"{HH}/webhook/not-a-secret", json={})).status_code == 404
    first = await client.post(f"{HH}/webhook/{secret}", json={"action_type": "NEW_NEGOTIATION"})
    assert first.status_code == 202, first.text
    second = await client.post(f"{HH}/webhook/{secret}", json={})
    assert second.json()["job_id"] == first.json()["job_id"]  # активная задача не дублируется

    org = await _org_id(token, client)
    async with get_session_maker()() as session:
        job = await session.get(Job, uuid.UUID(first.json()["job_id"]))
        assert job is not None and job.kind == HH_SYNC_JOB
        assert job.payload == {"organization_id": str(org), "reason": "webhook"}
        assert job.status == JobStatus.queued

    manual = await client.post(f"{HH}/sync", headers=bearer(token))
    assert manual.status_code == 202 and manual.json()["job_id"] == first.json()["job_id"]


# ----------------------------------------------------------- полный сценарий


async def test_full_dialog_scenario_on_fake(client: AsyncClient) -> None:
    _, token = await register(client, organization_name="Napoleon IT")
    await _connect_demo(client, token)
    org = await _org_id(token, client)

    vacancies = (await client.get(f"{HH}/vacancies", headers=bearer(token))).json()
    assert [v["id"] for v in vacancies] == ["hh-v-1001", "hh-v-1002", "hh-v-1003"]
    assert all(v["link"] is None for v in vacancies)

    link = await _import(client, token, "hh-v-1001")
    assert link["hh_title"] == "Python-разработчик (Backend)" and link["vacancy_status"] == "draft"
    local = (await client.get(f"/api/vacancies/{link['vacancy_id']}", headers=bearer(token))).json()
    assert local["title"] == "Python-разработчик (Backend)"
    assert "Требования:" in local["requirements"] and "от 3 лет" in local["requirements"]
    assert "Будет плюсом:" in local["requirements"]
    assert "Обязанности:" in local["description"] and "Требования" not in local["description"]
    assert local["skills"] == ["Python", "FastAPI", "PostgreSQL", "Docker", "asyncio"]
    assert (
        await client.post(f"{HH}/vacancies/hh-v-1001/import", headers=bearer(token))
    ).status_code == 409
    vacancies = (await client.get(f"{HH}/vacancies", headers=bearer(token))).json()
    assert vacancies[0]["link"]["id"] == link["id"]

    # До публикации локальной вакансии отклики импортируются, но диалог не стартует.
    stats = await _sync(org)
    assert stats["negotiations_new"] == 2 and stats["candidates_new"] == 2
    items = await _negotiations(client, token, link_id=link["id"])
    assert {n["state"] for n in items.values()} == {"new"}
    assert all(n["messages"] == [] for n in items.values())

    await _publish(client, token, link["vacancy_id"])

    # Синхронизация через очередь: задача hh.sync создаёт приветствия.
    queued = await client.post(f"{HH}/sync", headers=bearer(token))
    job = await _run_job(queued.json()["job_id"])
    assert job.status == JobStatus.succeeded, job.last_error
    items = await _negotiations(client, token, link_id=link["id"])
    anna, petr = items["hh-n-5001"], items["hh-n-5002"]
    assert anna["state"] == "greeting_sent" and petr["state"] == "greeting_sent"
    assert anna["candidate_name"] == "Смирнова Анна Игоревна"
    assert anna["candidate_email"] == "anna.smirnova@example.com"
    greeting = anna["messages"][0]
    assert greeting["role"] == "bot" and greeting["step"] == "greeting"
    assert "Анна" in greeting["text"] and "Python-разработчик (Backend)" in greeting["text"]
    assert "7 дней" in greeting["text"] and greeting["hh_message_id"] == "hh-chat-5001-b1"

    candidates = (await client.get("/api/candidates", headers=bearer(token))).json()
    by_email = {c["email"]: c for c in candidates}
    assert by_email["anna.smirnova@example.com"]["source"] == "hh"
    assert by_email["anna.smirnova@example.com"]["phone"] == "+7 916 123-45-67"
    assert by_email["petr.kozlov@example.com"]["external_ref"] == "hh:hh-r-9002"
    async with get_session_maker()() as session:
        row = await session.scalar(
            select(Candidate).where(
                Candidate.email == "anna.smirnova@example.com", Candidate.organization_id == org
            )
        )
        assert row is not None and "Финтех-стартап" in (row.resume_text or "")

    # Ответы кандидатов: Анна называет день, Пётр задаёт вопрос → переспрос.
    await _sync(org)
    items = await _negotiations(client, token, link_id=link["id"])
    anna, petr = items["hh-n-5001"], items["hh-n-5002"]
    today = utcnow().date()
    assert anna["state"] == "link_sent"
    assert anna["chosen_date"] == (today + timedelta(days=2)).isoformat()
    assert anna["interview_id"] and anna["interview_status"] == "invited"
    assert [m["role"] for m in anna["messages"]] == ["bot", "candidate", "bot"]
    link_message = anna["messages"][-1]
    assert link_message["step"] == "link" and "/i/" in link_message["text"]
    assert petr["state"] == "awaiting_slot" and _steps(petr) == ["greeting", "clarify"]

    async with get_session_maker()() as session:
        interview = await session.get(Interview, uuid.UUID(anna["interview_id"]))
        assert interview is not None
        assert interview.candidate_id == uuid.UUID(anna["candidate_id"])
        assert interview.external_ref == "hh:hh-n-5001"
        assert aware(interview.expires_at).date() == today + timedelta(days=3)
        # Токен ссылки из чата сохранён: напоминание повторит ту же ссылку.
        sent_token = re.search(r"/i/([A-Za-z0-9_-]+)", link_message["text"]).group(1)
        assert stored_link_token(interview) == sent_token
        email = await session.scalar(
            select(EmailMessage).where(EmailMessage.interview_id == interview.id)
        )
        assert email is not None and email.to_email == "anna.smirnova@example.com"
        assert link_message["text"].split("/i/", 1)[1].split()[0] in email.body_text

    # Пётр уточняет день — ссылка уходит; Анна ничего нового не получает.
    await _sync(org)
    items = await _negotiations(client, token, link_id=link["id"])
    petr = items["hh-n-5002"]
    assert petr["state"] == "link_sent" and _steps(petr) == ["greeting", "clarify", "link"]
    chosen = date.fromisoformat(petr["chosen_date"])
    assert chosen.weekday() == 4 and 1 <= (chosen - today).days <= 7
    assert petr["interview_id"] and petr["interview_status"] == "invited"

    # Повторные синхронизации ничего не дублируют.
    snapshot = _snapshot(items)
    for _ in range(2):
        await _sync(org)
    assert _snapshot(await _negotiations(client, token, link_id=link["id"])) == snapshot
    async with get_session_maker()() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(Candidate).where(Candidate.organization_id == org)
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(HhNegotiation)
                .where(HhNegotiation.organization_id == org)
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(Interview).where(Interview.organization_id == org)
            )
            == 2
        )

    # Интервью завершено — диалог помечается выполненным при следующей синхронизации.
    async with get_session_maker()() as session:
        interview = await session.get(Interview, uuid.UUID(anna["interview_id"]))
        assert interview is not None
        interview.status = InterviewStatus.completed
        await session.commit()
    await _sync(org)
    items = await _negotiations(client, token, candidate_id=anna["candidate_id"])
    assert items["hh-n-5001"]["state"] == "done"

    # Карточка кандидата видит свой диалог, чужой кандидат — ничего.
    assert list(items) == ["hh-n-5001"]
    assert await _negotiations(client, token, candidate_id=str(uuid.uuid4())) == {}


async def test_decline_needs_recruiter_and_take_over(client: AsyncClient) -> None:
    _, owner = await register(client)
    recruiter = await _member(client, owner, "recruiter")
    await _connect_demo(client, owner)
    org = await _org_id(owner, client)
    link = await _import_published(client, recruiter, "hh-v-1002")

    await _sync(org)  # приветствия
    await _sync(org)  # Ольга отказывается, Сергей пишет «???» → переспрос
    items = await _negotiations(client, recruiter, link_id=link["id"])
    olga, sergey = items["hh-n-5003"], items["hh-n-5004"]
    assert olga["state"] == "declined" and _steps(olga) == ["greeting"]
    assert olga["interview_id"] is None
    assert sergey["state"] == "awaiting_slot" and _steps(sergey) == ["greeting", "clarify"]

    await _sync(org)  # «не знаю пока» → нужен рекрутер
    items = await _negotiations(client, recruiter, link_id=link["id"])
    sergey = items["hh-n-5004"]
    assert sergey["state"] == "needs_recruiter" and _steps(sergey) == ["greeting", "clarify"]
    assert [m["text"] for m in sergey["messages"] if m["role"] == "candidate"] == [
        "???",
        "не знаю пока",
    ]

    # Отказавшемуся ссылку отправить нельзя, «взять в работу» — только незавершённый диалог.
    refused = await client.post(
        f"{HH}/negotiations/{olga['id']}/take-over", json={}, headers=bearer(recruiter)
    )
    assert refused.status_code == 409
    taken = await client.post(
        f"{HH}/negotiations/{sergey['id']}/take-over", json={"days": 3}, headers=bearer(recruiter)
    )
    assert taken.status_code == 200, taken.text
    body = taken.json()
    assert body["state"] == "link_sent" and _steps(body) == ["greeting", "clarify", "link"]
    assert body["interview_id"] and body["chosen_date"] is None
    async with get_session_maker()() as session:
        interview = await session.get(Interview, uuid.UUID(body["interview_id"]))
        assert interview is not None
        assert aware(interview.expires_at).date() == (utcnow() + timedelta(days=3)).date()
    # Повторная синхронизация состояние не откатывает и ссылку не дублирует.
    await _sync(org)
    again = (await _negotiations(client, recruiter, link_id=link["id"]))["hh-n-5004"]
    assert again["state"] == "link_sent" and _steps(again) == ["greeting", "clarify", "link"]


async def test_dialog_settings_and_disabled_dialog(client: AsyncClient) -> None:
    _, token = await register(client)
    await _connect_demo(client, token)
    org = await _org_id(token, client)
    link = await _import_published(client, token, "hh-v-1003")

    dialog = (await client.get(f"{HH}/links/{link['id']}/dialog", headers=bearer(token))).json()
    assert dialog["enabled"] is True and dialog["max_days"] == 7
    assert set(dialog["placeholders"]) == {
        "candidate_name",
        "vacancy_title",
        "link",
        "days",
        "date",
    }
    assert "Data Scientist (NLP / LLM)" in dialog["preview"]["greeting"]
    assert "{candidate_name}" not in dialog["preview"]["greeting"]

    updated = await client.put(
        f"{HH}/links/{link['id']}/dialog",
        json={
            **{k: dialog[k] for k in ("clarify", "link")},
            "enabled": False,
            "max_days": 3,
            "greeting": "Привет, {candidate_name}! Когда удобно в ближайшие {days} дня? {unknown}",
        },
        headers=bearer(token),
    )
    assert updated.status_code == 200, updated.text
    assert (
        updated.json()["preview"]["greeting"]
        == "Привет, Анна! Когда удобно в ближайшие 3 дня? {unknown}"
    )
    assert (await client.get(f"{HH}/links", headers=bearer(token))).json()[0][
        "dialog_enabled"
    ] is False

    await _sync(org)
    maria = (await _negotiations(client, token, link_id=link["id"]))["hh-n-5005"]
    assert maria["state"] == "new" and maria["messages"] == []

    await client.put(
        f"{HH}/links/{link['id']}/dialog",
        json={**updated.json(), "enabled": True},
        headers=bearer(token),
    )
    await _sync(org)
    maria = (await _negotiations(client, token, link_id=link["id"]))["hh-n-5005"]
    assert maria["state"] == "greeting_sent"
    assert (
        maria["messages"][0]["text"] == "Привет, Мария! Когда удобно в ближайшие 3 дня? {unknown}"
    )
    await _sync(org)  # Мария не отвечает — состояние не меняется
    maria = (await _negotiations(client, token, link_id=link["id"]))["hh-n-5005"]
    assert maria["state"] == "greeting_sent" and len(maria["messages"]) == 1


async def test_link_existing_vacancy(client: AsyncClient) -> None:
    _, token = await register(client)
    await _connect_demo(client, token)
    local = (
        await client.post("/api/vacancies", json={"title": "Своя вакансия"}, headers=bearer(token))
    ).json()
    linked = await client.post(
        f"{HH}/vacancies/hh-v-1002/link", json={"vacancy_id": local["id"]}, headers=bearer(token)
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["vacancy_title"] == "Своя вакансия"
    assert linked.json()["hh_title"] == "Frontend-разработчик (React / Next.js)"
    missing = await client.post(
        f"{HH}/vacancies/hh-v-1002/link",
        json={"vacancy_id": str(uuid.uuid4())},
        headers=bearer(token),
    )
    assert missing.status_code == 404
    assert (
        await client.post(f"{HH}/vacancies/hh-v-9999/import", headers=bearer(token))
    ).status_code == 404


async def test_periodic_job_reschedules_itself() -> None:
    async with get_session_maker()() as session:
        job = await ensure_periodic_sync(session)
        await session.commit()
        assert job.dedupe_key and job.dedupe_key.startswith("hh:sync:periodic:")
        assert (await ensure_periodic_sync(session)).id == job.id

    async def heartbeat() -> bool:
        return True

    ctx = JobContext(
        job_id=job.id,
        kind=HH_SYNC_JOB,
        attempt=1,
        worker_id="w-test",
        session_maker=get_session_maker(),
        _heartbeat=heartbeat,
    )
    result = await hh_sync_job({"periodic": True}, ctx)
    assert result is not None and "connections" in result
    async with get_session_maker()() as session:
        next_job = await session.get(Job, uuid.UUID(result["next_job_id"]))
        assert next_job is not None and next_job.id != job.id
        interval = timedelta(minutes=get_settings().HH_SYNC_INTERVAL_MINUTES)
        assert aware(next_job.run_after) - utcnow() > interval - timedelta(minutes=1)
        assert next_job.payload == {"periodic": True}


async def test_sync_jobs_do_not_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Периодическая и внеочередная синхронизации выполняются по очереди.

    Две параллельные синхронизации читали один ответ кандидата и обе выпускали
    ссылку: в чат уходила одна, а в базе оставался хеш другой.
    """
    import asyncio

    from leonit.hh import jobs as hh_jobs

    timeline: list[str] = []

    async def fake_sync(session: Any, *, organization_id: Any = None) -> dict[str, Any]:
        timeline.append(f"enter:{organization_id}")
        await asyncio.sleep(0.02)
        timeline.append(f"exit:{organization_id}")
        return {"connections": 0, "failed": 0}

    monkeypatch.setattr(hh_jobs, "sync_organizations", fake_sync)

    async def heartbeat() -> bool:
        return True

    ctx = JobContext(
        job_id=uuid.uuid4(),
        kind=HH_SYNC_JOB,
        attempt=1,
        worker_id="w-test",
        session_maker=get_session_maker(),
        _heartbeat=heartbeat,
    )
    org = uuid.uuid4()
    results = await asyncio.gather(
        hh_sync_job({"organization_id": str(org)}, ctx),
        hh_sync_job({"organization_id": str(org)}, ctx),
    )
    assert all(result is not None and result["connections"] == 0 for result in results)
    assert timeline == [f"enter:{org}", f"exit:{org}", f"enter:{org}", f"exit:{org}"]


# ------------------------------------------------------------- разбор срока


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Добрый день! Удобно послезавтра", ("date", 2)),
        ("завтра в 15.30 смогу", ("date", 1)),
        ("сегодня", ("date", 0)),
        ("давайте через 3 дня", ("date", 3)),
        ("через неделю", ("date", 7)),
        ("Спасибо, не интересно", ("declined", None)),
        ("нет, спасибо, я уже нашёл работу", ("declined", None)),
        ("???", ("unknown", None)),
        ("не знаю пока", ("unknown", None)),
    ],
)
def test_slot_rules(text: str, expected: tuple[str, int | None]) -> None:
    today = date(2026, 9, 3)  # четверг
    result = parse_slot_rules(text, today=today)
    kind, offset = expected
    assert result.kind == kind
    if offset is not None:
        assert result.date == today + timedelta(days=offset)


def test_slot_rules_weekdays_and_dates() -> None:
    today = date(2026, 9, 3)  # четверг
    assert parse_slot_rules("в пятницу", today=today).date == date(2026, 9, 4)
    assert parse_slot_rules("в четверг", today=today).date == date(2026, 9, 10)
    assert parse_slot_rules("во вторник вечером", today=today).date == date(2026, 9, 8)
    assert parse_slot_rules("15.09", today=today).date == date(2026, 9, 15)
    assert parse_slot_rules("15 сентября", today=today).date == date(2026, 9, 15)
    assert parse_slot_rules("2026-09-20", today=today).date == date(2026, 9, 20)
    assert parse_slot_rules("1 января", today=today).date == date(2027, 1, 1)


async def test_extract_slot_prefers_model_then_falls_back() -> None:
    today = date(2026, 9, 3)
    by_model = ScriptedLLM(json.dumps({"intent": "date", "date": "2026-09-05"}))
    result = await extract_slot("могу в субботу днём", today=today, max_days=7, llm=by_model)
    assert result.kind == "date" and result.date == date(2026, 9, 5) and by_model.calls == 1

    declined = ScriptedLLM(json.dumps({"intent": "declined", "date": None}))
    assert (
        await extract_slot("я передумал", today=today, max_days=7, llm=declined)
    ).kind == "declined"

    # Дата от модели вне окна — берём правила; правила вне окна — unknown.
    far = ScriptedLLM(json.dumps({"intent": "date", "date": "2026-12-01"}))
    fallback = await extract_slot("послезавтра", today=today, max_days=7, llm=far)
    assert fallback.kind == "date" and fallback.date == date(2026, 9, 5)
    assert (await extract_slot("через 20 дней", today=today, max_days=7, llm=far)).kind == "unknown"

    broken = ScriptedLLM(error=RuntimeError("provider down"))
    assert (await extract_slot("завтра", today=today, max_days=7, llm=broken)).date == date(
        2026, 9, 4
    )
    assert (await extract_slot("завтра", today=today, max_days=7, llm=None)).date == date(
        2026, 9, 4
    )


# ----------------------------------------------------- реальный клиент (HTTP)


def _settings() -> Settings:
    return Settings(
        HH_CLIENT_ID="cid",
        HH_CLIENT_SECRET="csec",
        HH_API_BASE="https://api.hh.test",
        HH_OAUTH_BASE="https://hh.test",
        PUBLIC_URL="https://app.test",
        HH_USER_AGENT="LeonIT-test/1.0 (test@example.com)",
    )


def _tokens(access: str = "access-1", *, expired: bool = False) -> HhTokens:
    delta = timedelta(hours=-1) if expired else timedelta(hours=1)
    return HhTokens(access_token=access, refresh_token="refresh-1", expires_at=utcnow() + delta)


async def test_oauth_exchange_sends_pkce_and_client_secret() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        tokens = await HhOAuth(_settings(), http=http).exchange_code("code-1", code_verifier="ver")
    assert tokens.access_token == "a1" and tokens.refresh_token == "r1"
    assert aware(tokens.expires_at) - utcnow() < timedelta(hours=1, minutes=1)
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://api.hh.test/token"
    form = parse_qs(request.content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["code-1"]
    assert form["code_verifier"] == ["ver"] and form["client_secret"] == ["csec"]
    assert form["redirect_uri"] == ["https://app.test/api/integrations/hh/callback"]
    assert request.headers["HH-User-Agent"] == "LeonIT-test/1.0 (test@example.com)"

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "code expired"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as http:
        with pytest.raises(HhAuthError, match="code expired"):
            await HhOAuth(_settings(), http=http).exchange_code("bad", code_verifier="ver")


async def test_real_client_refreshes_on_401_and_persists_tokens() -> None:
    saved: list[HhTokens] = []
    seen: list[httpx.Request] = []

    async def on_tokens(tokens: HhTokens) -> None:
        saved.append(tokens)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/token":
            assert parse_qs(request.content.decode())["refresh_token"] == ["refresh-1"]
            return httpx.Response(
                200,
                json={"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 600},
            )
        if request.headers["Authorization"] == "Bearer access-1":
            return httpx.Response(
                401, json={"errors": [{"type": "oauth", "value": "token_expired"}]}
            )
        return httpx.Response(
            200,
            json={
                "id": "u1",
                "employer": {"id": "e1", "name": "ООО Тест"},
                "manager": {"id": "m1"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RealHhClient(_settings(), _tokens(), on_tokens=on_tokens, http=http)
        employer = await client.me()
    assert (
        employer.id == "e1" and employer.name == "ООО Тест" and employer.manager_account_id == "m1"
    )
    assert [r.url.path for r in seen] == ["/me", "/token", "/me", "/manager_accounts/mine"]
    assert saved and saved[0].access_token == "access-2" and saved[0].refresh_token == "refresh-2"
    assert client.tokens.access_token == "access-2"

    # Истёкший по сроку токен обновляется до первого запроса.
    seen.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RealHhClient(_settings(), _tokens(expired=True), http=http)
        await client.me()
    assert [r.url.path for r in seen] == ["/token", "/me", "/manager_accounts/mine"]

    def revoked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errors": [{"type": "oauth", "value": "token_revoked"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(revoked)) as http:
        with pytest.raises(HhAuthError, match="отозвана"):
            await RealHhClient(_settings(), _tokens(), http=http).me()


async def test_real_client_retries_once_on_429_with_retry_after() -> None:
    attempts: list[str] = []
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        if len(attempts) == 1:
            return httpx.Response(
                429, headers={"Retry-After": "2"}, json={"description": "rate limit"}
            )
        return httpx.Response(
            200, json={"id": "v1", "name": "Вакансия", "key_skills": [{"name": "Python"}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RealHhClient(_settings(), _tokens(), http=http, sleep=sleep)
        vacancy = await client.vacancy("v1")
    assert vacancy.name == "Вакансия" and vacancy.key_skills == ["Python"]
    assert attempts == ["/vacancies/v1", "/vacancies/v1"] and slept == [2.0]

    def always(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(always)) as http:
        with pytest.raises(Exception, match="HTTP 429"):
            await RealHhClient(_settings(), _tokens(), http=http, sleep=sleep).vacancy("v1")


async def test_real_client_sends_idempotent_messages_and_treats_409_as_sent() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/common/chats/chat-1/messages"
        if request.method == "GET":
            # Формат /common/chats/{id}/messages: список в messages, текст в payload,
            # автор в sender_display_info.role, время в creation_time.
            assert dict(request.url.params) == {
                "order": "next",
                "limit": "50",
                "start_message_id": "m0",
            }
            return httpx.Response(
                200,
                json={
                    "id": "chat-1",
                    "has_more": False,
                    "messages": [
                        {
                            "id": "m0",
                            "creation_time": "2026-09-03T09:59:00+0300",
                            "sender_display_info": {"role": "EMPLOYER", "name": "Максим"},
                            "payload": {"text": "старое"},
                            "type": "SIMPLE",
                        },
                        {
                            "id": "m1",
                            "creation_time": "2026-09-03T10:00:00+0300",
                            "sender_display_info": {"role": "APPLICANT", "name": "Григорий"},
                            "payload": {"text": "завтра"},
                            "type": "SIMPLE",
                        },
                    ],
                },
            )
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 2:
            return httpx.Response(409, json={"description": "duplicate idempotency key"})
        return httpx.Response(
            201, json={"id": "m2", "author": {"participant_type": "employer"}, "text": body["text"]}
        )

    key = idempotency_key(uuid.uuid4(), "greeting")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RealHhClient(_settings(), _tokens(), http=http)
        sent = await client.send_message("chat-1", "Здравствуйте!", idempotency_key=key)
        again = await client.send_message("chat-1", "Здравствуйте!", idempotency_key=key)
        messages = await client.messages("chat-1", after_message_id="m0")
    assert sent is not None and sent.id == "m2" and again is None
    assert bodies[0] == {"idempotency_key": key, "text": "Здравствуйте!", "is_automated": True}
    assert uuid.UUID(key) and bodies[1]["idempotency_key"] == key
    assert [m.id for m in messages] == ["m1"] and messages[0].author == "applicant"
    assert messages[0].text == "завтра"
    assert messages[0].created_at is not None and messages[0].created_at.hour == 10


def test_parse_message_accepts_legacy_negotiation_format() -> None:
    from leonit.hh.client import parse_message

    legacy = parse_message(
        {
            "id": "m1",
            "author": {"participant_type": "applicant"},
            "text": "завтра",
            "created_at": "2026-09-03T10:00:00+03:00",
        }
    )
    assert (legacy.id, legacy.author, legacy.text) == ("m1", "applicant", "завтра")
    assert legacy.created_at is not None and legacy.created_at.hour == 10
    empty = parse_message({"id": "m2", "sender_display_info": {"role": "APPLICANT"}, "payload": {}})
    assert (empty.author, empty.text, empty.created_at) == ("applicant", "", None)


async def test_connect_with_imported_token_never_refreshes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Готовый токен другого приложения подключается через /me и не обновляется сам."""
    from leonit.hh.service import HhService

    real = Settings(
        HH_CLIENT_ID="cid",
        HH_CLIENT_SECRET="csec",
        HH_API_BASE="https://api.hh.test",
        HH_OAUTH_BASE="https://hh.test",
    )
    monkeypatch.setattr("leonit.hh.service.get_settings", lambda: real)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/me":
            return httpx.Response(
                200,
                json={
                    "id": "u-1",
                    "employer": {"id": "12980144", "name": "Napoleon IT"},
                    "manager": {"id": "m-7"},
                },
            )
        return httpx.Response(500, json={"description": "unexpected"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        HhService, "_real_client", lambda self, tokens: RealHhClient(real, tokens, http=http)
    )
    _, owner = await register(client)

    # Без access_token — 422; чужой/просроченный срок — 422.
    bad = await client.post(
        f"{HH}/connect-token", json={"access_token": "short"}, headers=bearer(owner)
    )
    assert bad.status_code == 422
    expired = await client.post(
        f"{HH}/connect-token",
        json={"access_token": "imported-access-token-1", "expires_at": "2020-01-01T00:00:00Z"},
        headers=bearer(owner),
    )
    assert expired.status_code == 422

    response = await client.post(
        f"{HH}/connect-token",
        json={"access_token": "imported-access-token-1"},
        headers=bearer(owner),
    )
    assert response.status_code == 200, response.text
    connection = response.json()["connection"]
    assert connection["status"] == "connected" and connection["mode"] == "real"
    assert connection["employer_name"] == "Napoleon IT" and connection["employer_id"] == "12980144"
    assert connection["token_refreshable"] is False
    assert aware(datetime.fromisoformat(connection["expires_at"])) - utcnow() > timedelta(days=13)
    # Только /me и список аккаунтов с нашим токеном; за /token (refresh) клиент не ходил.
    paths = [r.url.path for r in seen]
    assert paths[0] == "/me" and "/token" not in paths
    assert set(paths) == {"/me", "/manager_accounts/mine"}
    assert seen[0].headers["Authorization"] == "Bearer imported-access-token-1"
    assert "X-Manager-Account-Id" not in seen[0].headers

    org = await _org_id(owner, client)
    async with get_session_maker()() as session:
        row = await session.scalar(select(HhConnection).where(HhConnection.organization_id == org))
        assert row is not None
        assert get_secret_box().decrypt(row.access_token_enc) == "imported-access-token-1"
        # Без refresh_token поле пустое: клиент не пойдёт обновлять пару.
        assert row.refresh_token_enc == ""
        assert row.manager_account_id == "m-7"
    await http.aclose()


async def test_me_prefers_manager_account_from_mine_list() -> None:
    """X-Manager-Account-Id — это id аккаунта из /manager_accounts/mine, а не manager.id."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/me":
            return httpx.Response(
                200,
                json={
                    "id": "194470745",
                    "employer": {"id": "12980144", "name": "ООО Тест"},
                    "manager": {"id": "77"},
                },
            )
        if request.url.path == "/manager_accounts/mine":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "555", "employer": {"id": "other", "name": "Чужой"}},
                        {"id": "194470745", "employer": {"id": "12980144", "name": "ООО Тест"}},
                    ]
                },
            )
        return httpx.Response(404, json={"description": "not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        employer = await RealHhClient(_settings(), _tokens(), http=http).me()
    assert employer.manager_account_id == "194470745"
    assert employer.id == "12980144" and employer.user_id == "194470745"
