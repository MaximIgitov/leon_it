from __future__ import annotations

import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from leonit.candidates.models import ConsentRecord, Interview
from leonit.core.db import get_session_maker
from leonit.core.time import utcnow
from leonit.jobs import service as jobs
from leonit.jobs.models import JobStatus
from leonit.notifications.jobs import send_email_job
from leonit.notifications.models import EmailMessage
from tests.helpers import bearer, create_invite, invite_token_from_url, register


async def _published_vacancy(
    client: AsyncClient, token: str, title: str = "Python-разработчик"
) -> dict:
    response = await client.post(
        "/api/vacancies", json={"title": title, "description": "Бэкенд"}, headers=bearer(token)
    )
    vacancy = response.json()
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={"questions": [{"text": "Расскажите о себе"}, {"text": "Что такое GIL?"}]},
        headers=bearer(token),
    )
    published = await client.post(f"/api/vacancies/{vacancy['id']}/publish", headers=bearer(token))
    assert published.status_code == 200, published.text
    return published.json()


async def _invite(client: AsyncClient, token: str, vacancy_id: str, email: str) -> dict:
    response = await client.post(
        "/api/interviews",
        json={"vacancy_id": vacancy_id, "full_name": "Иван Кандидат", "email": email},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _token(link: str) -> str:
    return link.rsplit("/i/", 1)[1]


async def test_create_candidate_and_duplicate(client: AsyncClient) -> None:
    _, token = await register(client)
    created = await client.post(
        "/api/candidates",
        json={"full_name": " Анна Иванова ", "email": "Anna@Example.com"},
        headers=bearer(token),
    )
    assert created.status_code == 201
    assert created.json()["full_name"] == "Анна Иванова"
    assert created.json()["email"] == "anna@example.com"
    duplicate = await client.post(
        "/api/candidates",
        json={"full_name": "Анна", "email": "anna@example.com"},
        headers=bearer(token),
    )
    assert duplicate.status_code == 409
    found = await client.get("/api/candidates?search=иван", headers=bearer(token))
    assert [c["email"] for c in found.json()] == ["anna@example.com"]


async def test_bulk_create_parses_lines_and_invites(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    response = await client.post(
        "/api/candidates/bulk",
        json={
            "text": (
                "Пётр Петров, petr@example.com\nolga@example.com\nне строка\n\n"
                "Пётр, petr@example.com"
            ),
            "vacancy_id": vacancy["id"],
        },
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(c["email"] for c in body["created"]) == ["olga@example.com", "petr@example.com"]
    assert (
        next(c for c in body["created"] if c["email"] == "olga@example.com")["full_name"] == "olga"
    )
    assert body["skipped_lines"] == 1
    assert body["invited"] == 2
    assert all(c["last_interview_status"] == "invited" for c in body["created"])


async def test_invite_requires_published_vacancy(client: AsyncClient) -> None:
    _, token = await register(client)
    draft = (
        await client.post("/api/vacancies", json={"title": "Черновик"}, headers=bearer(token))
    ).json()
    response = await client.post(
        "/api/interviews",
        json={"vacancy_id": draft["id"], "full_name": "Х", "email": "x@example.com"},
        headers=bearer(token),
    )
    assert response.status_code == 422


async def test_invite_with_malformed_ids_is_422(client: AsyncClient) -> None:
    """Неверные UUID отсекает схема: 422 с указанием поля, а не ValueError и 500 из сервиса."""
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    bad_vacancy = await client.post(
        "/api/interviews",
        json={"vacancy_id": "not-a-uuid", "full_name": "Х", "email": "x@example.com"},
        headers=bearer(token),
    )
    assert bad_vacancy.status_code == 422, bad_vacancy.text
    assert ["body", "vacancy_id"] in [e["loc"] for e in bad_vacancy.json()["detail"]]

    bad_candidate = await client.post(
        "/api/interviews",
        json={"vacancy_id": vacancy["id"], "candidate_id": "nope"},
        headers=bearer(token),
    )
    assert bad_candidate.status_code == 422, bad_candidate.text
    assert ["body", "candidate_id"] in [e["loc"] for e in bad_candidate.json()["detail"]]

    bad_bulk = await client.post(
        "/api/candidates/bulk",
        json={"text": "x@example.com", "vacancy_id": "not-a-uuid"},
        headers=bearer(token),
    )
    assert bad_bulk.status_code == 422, bad_bulk.text

    # Пустая строка из диалога кабинета (вакансия не выбрана) означает «без приглашений».
    no_vacancy = await client.post(
        "/api/candidates/bulk",
        json={"text": "y@example.com", "vacancy_id": ""},
        headers=bearer(token),
    )
    assert no_vacancy.status_code == 200, no_vacancy.text
    assert no_vacancy.json()["invited"] == 0
    assert [c["email"] for c in no_vacancy.json()["created"]] == ["y@example.com"]


async def test_invite_flow_link_shown_once_and_email_queued(client: AsyncClient) -> None:
    _, token = await register(client, organization_name="Napoleon IT")
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    assert interview["status"] == "invited"
    assert interview["link"].startswith("http") and "/i/" in interview["link"]
    assert interview["vacancy_title"] == "Python-разработчик"

    listed = (
        await client.get(f"/api/interviews?vacancy_id={vacancy['id']}", headers=bearer(token))
    ).json()
    assert listed[0]["id"] == interview["id"]
    assert listed[0]["link"] is None

    duplicate = await client.post(
        "/api/interviews",
        json={"vacancy_id": vacancy["id"], "candidate_id": interview["candidate_id"]},
        headers=bearer(token),
    )
    assert duplicate.status_code == 409

    async with get_session_maker()() as session:
        email = await session.scalar(
            select(EmailMessage).where(EmailMessage.interview_id == uuid.UUID(interview["id"]))
        )
        assert email is not None
        assert email.kind == "interview.invitation"
        assert interview["link"] in email.body_text
        assert "Python-разработчик" in email.subject
        assert email.status.value == "queued"
        # В очереди могут лежать письма из других тестов — берём именно наше.
        job = None
        for _ in range(50):
            candidate_job = await jobs.claim_next(session, "test-worker", kinds=["email.send"])
            assert candidate_job is not None
            if candidate_job.payload["email_id"] == str(email.id):
                job = candidate_job
                break
            await jobs.complete(session, candidate_job.id, None, worker_id="test-worker")
        assert job is not None
        await session.commit()
    # Обработчик доставляет консольным транспортом и помечает письмо отправленным.
    from leonit.jobs.registry import JobContext

    async def _hb() -> bool:
        return True

    ctx = JobContext(
        job_id=job.id,
        kind=job.kind,
        attempt=1,
        worker_id="test-worker",
        session_maker=get_session_maker(),
        _heartbeat=_hb,
    )
    result = await send_email_job(job.payload, ctx)
    assert result == {"status": "sent", "provider": "console"}
    async with get_session_maker()() as session:
        await jobs.complete(session, job.id, result, worker_id="test-worker")
        refreshed = await session.get(EmailMessage, email.id)
        assert refreshed.status.value == "sent"
        done = await session.get(type(job), job.id)
        assert done.status == JobStatus.succeeded

    emails = (await client.get("/api/organization/emails", headers=bearer(token))).json()
    assert emails[0]["to_email"] == "cand@example.com"
    assert emails[0]["status"] == "sent"


async def test_public_invitation_opens_and_consent_records(client: AsyncClient) -> None:
    _, token = await register(client, organization_name="Napoleon IT")
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    link_token = _token(interview["link"])

    opened = await client.get(f"/api/public/invitations/{link_token}")
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["status"] == "opened"
    assert body["needs_consent"] is True
    assert body["organization_name"] == "Napoleon IT"
    assert body["question_count"] == 2
    assert body["estimated_minutes"] >= 3
    slugs = [doc["slug"] for doc in body["consent_documents"]]
    assert slugs == ["personal-data-consent", "privacy-policy", "newsletter-consent"]
    assert body["candidate_email"] == "cand@example.com"

    refused = await client.post(
        f"/api/public/invitations/{link_token}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": False,
        },
    )
    assert refused.status_code == 422

    versions = {doc["slug"]: doc["version"] for doc in body["consent_documents"]}
    accepted = await client.post(
        f"/api/public/invitations/{link_token}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "newsletter_accepted": True,
            "document_versions": versions,
        },
        headers={"User-Agent": "pytest-browser"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "consented"
    assert accepted.json()["needs_consent"] is False

    async with get_session_maker()() as session:
        records = list(
            await session.scalars(
                select(ConsentRecord).where(
                    ConsentRecord.interview_id == uuid.UUID(interview["id"])
                )
            )
        )
        by_slug = {r.slug: r for r in records}
        assert set(by_slug) == {"personal-data-consent", "privacy-policy", "newsletter-consent"}
        assert by_slug["personal-data-consent"].accepted is True
        assert by_slug["newsletter-consent"].accepted is True
        assert len(by_slug["privacy-policy"].document_hash) == 64
        assert by_slug["privacy-policy"].user_agent == "pytest-browser"
        row = await session.get(Interview, uuid.UUID(interview["id"]))
        assert row.newsletter_opt_in is True and row.consent_full_name == "Иван Кандидат"

    # Повторная отправка согласия идемпотентна, статус не откатывается.
    again = await client.post(
        f"/api/public/invitations/{link_token}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
        },
    )
    assert again.status_code == 200 and again.json()["status"] == "consented"


async def test_consent_rejects_stale_document_version(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    response = await client.post(
        f"/api/public/invitations/{_token(interview['link'])}/consent",
        json={
            "full_name": "Иван",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "document_versions": {"privacy-policy": "1999-01-01"},
        },
    )
    assert response.status_code == 409


async def test_expired_link_and_resend(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    async with get_session_maker()() as session:
        await session.execute(
            update(Interview)
            .where(Interview.id == uuid.UUID(interview["id"]))
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
        await session.commit()
    expired = await client.get(f"/api/public/invitations/{_token(interview['link'])}")
    assert expired.status_code == 200 and expired.json()["status"] == "expired"

    resent = await client.post(f"/api/interviews/{interview['id']}/resend", headers=bearer(token))
    assert resent.status_code == 200, resent.text
    assert resent.json()["status"] == "invited"
    assert resent.json()["link"] and resent.json()["link"] != interview["link"]
    old = await client.get(f"/api/public/invitations/{_token(interview['link'])}")
    assert old.status_code == 404
    fresh = await client.get(f"/api/public/invitations/{_token(resent.json()['link'])}")
    assert fresh.status_code == 200 and fresh.json()["status"] == "opened"


async def test_cancel_interview_blocks_link(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    cancelled = await client.post(
        f"/api/interviews/{interview['id']}/cancel", headers=bearer(token)
    )
    assert cancelled.json()["status"] == "cancelled"
    page = await client.get(f"/api/public/invitations/{_token(interview['link'])}")
    assert page.status_code == 200 and page.json()["status"] == "cancelled"
    consent = await client.post(
        f"/api/public/invitations/{_token(interview['link'])}/consent",
        json={
            "full_name": "И",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
        },
    )
    assert consent.status_code == 409


async def test_hiring_manager_scope_for_candidates_and_interviews(client: AsyncClient) -> None:
    _, owner = await register(client)
    allowed = await _published_vacancy(client, owner, "Разрешённая")
    hidden = await _published_vacancy(client, owner, "Скрытая")
    await _invite(client, owner, allowed["id"], "a@example.com")
    await _invite(client, owner, hidden["id"], "b@example.com")
    invite = await create_invite(
        client, owner, role="hiring_manager", vacancy_scope=[allowed["id"]]
    )
    _, manager = await register(client, invite_token=invite_token_from_url(invite["url"]))

    candidates = (await client.get("/api/candidates", headers=bearer(manager))).json()
    assert [c["email"] for c in candidates] == ["a@example.com"]
    interviews = (await client.get("/api/interviews", headers=bearer(manager))).json()
    assert [i["candidate_email"] for i in interviews] == ["a@example.com"]
    forbidden = await client.get(
        f"/api/interviews?vacancy_id={hidden['id']}", headers=bearer(manager)
    )
    assert forbidden.status_code == 403
    cannot_invite = await client.post(
        "/api/interviews",
        json={"vacancy_id": allowed["id"], "full_name": "Н", "email": "n@example.com"},
        headers=bearer(manager),
    )
    assert cannot_invite.status_code == 403


async def test_unknown_public_token_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/public/invitations/nope")).status_code == 404
