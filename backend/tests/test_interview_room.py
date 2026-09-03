from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from leonit.core.db import get_session_maker
from leonit.interviews.models import InterviewEvent
from leonit.jobs.models import Job
from leonit.notifications.models import EmailMessage
from tests.helpers import bearer, register
from tests.test_candidates import _invite, _published_vacancy, _token

CHUNK = b"\x1aE\xdf\xa3" + b"x" * 1000


async def _consented(client: AsyncClient) -> tuple[str, dict, str, str]:
    _, token = await register(client, organization_name="Napoleon IT")
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    link = _token(interview["link"])
    page = (await client.get(f"/api/public/invitations/{link}")).json()
    response = await client.post(
        f"/api/public/invitations/{link}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "document_versions": {d["slug"]: d["version"] for d in page["consent_documents"]},
        },
    )
    assert response.status_code == 200, response.text
    return token, interview, link, vacancy["id"]


async def _upload_answer(client: AsyncClient, link: str, index: int, chunks: int = 2) -> dict:
    created = await client.post(
        f"/api/public/invitations/{link}/questions/{index}/answers",
        json={"mime_type": "video/webm;codecs=vp9,opus"},
    )
    assert created.status_code == 201, created.text
    answer = created.json()["answer"]
    offset = 0
    for _ in range(chunks):
        response = await client.patch(
            f"/api/public/invitations/{link}/answers/{answer['id']}/chunks",
            content=CHUNK,
            headers={
                "Upload-Offset": str(offset),
                "Content-Type": "application/offset+octet-stream",
            },
        )
        assert response.status_code == 200, response.text
        offset = response.json()["upload_offset"]
    completed = await client.post(
        f"/api/public/invitations/{link}/answers/{answer['id']}/complete",
        json={"size": offset, "client_duration_ms": 4200},
    )
    assert completed.status_code == 200, completed.text
    return completed.json()


async def test_start_requires_consent_and_snapshots_questions(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "x@example.com")
    link = _token(interview["link"])
    await client.get(f"/api/public/invitations/{link}")
    early = await client.post(f"/api/public/invitations/{link}/start", json={})
    assert early.status_code == 409


async def test_full_room_flow(client: AsyncClient) -> None:
    token, interview, link, _ = await _consented(client)

    started = await client.post(
        f"/api/public/invitations/{link}/start",
        json={"client_info": {"user_agent": "pytest", "screen": "1280x720"}},
    )
    assert started.status_code == 200, started.text
    state = started.json()
    assert state["status"] == "in_progress"
    assert state["total_questions"] == 2
    assert state["current_question_index"] == 0
    # Будущие вопросы не выдаются, подсказки оценщику — тоже.
    assert [q["index"] for q in state["questions"]] == [0]
    assert "expected_points" not in state["questions"][0]
    assert state["settings"]["prep_seconds"] == 30

    # Повторный старт идемпотентен.
    assert (await client.post(f"/api/public/invitations/{link}/start", json={})).status_code == 200

    reveal = await client.post(f"/api/public/invitations/{link}/questions/0/reveal")
    assert reveal.status_code == 200, reveal.text
    body = reveal.json()
    assert body["question"]["text"] == "Расскажите о себе"
    assert body["audio_url"].startswith("/api/media/")
    first_revealed = body["revealed_at"]
    again = (await client.post(f"/api/public/invitations/{link}/questions/0/reveal")).json()
    assert again["revealed_at"] == first_revealed
    # Озвучка доступна по подписанной ссылке.
    audio = await client.get(body["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"].startswith("audio/")

    locked = await client.post(f"/api/public/invitations/{link}/questions/1/reveal")
    assert locked.status_code == 409

    answer = await _upload_answer(client, link, 0)
    assert answer["status"] == "uploaded"
    assert answer["media_size"] == 2 * len(CHUNK)
    assert answer["is_final"] is True
    assert answer["duration_ms"] is not None

    too_early_next = await client.post(f"/api/public/invitations/{link}/next")
    assert too_early_next.status_code == 200
    assert too_early_next.json()["current_question_index"] == 1

    events = await client.post(
        f"/api/public/invitations/{link}/events",
        json={
            "events": [
                {"kind": "visibility_hidden", "at_client_ms": 1000, "question_index": 1},
                {
                    "kind": "paste",
                    "at_client_ms": 1500,
                    "question_index": 1,
                    "payload": {"length": 40},
                },
                {"kind": "made_up", "at_client_ms": 1600},
            ]
        },
    )
    assert events.json() == {"accepted": 2, "ignored": 1}

    await client.post(f"/api/public/invitations/{link}/questions/1/reveal")
    await _upload_answer(client, link, 1, chunks=1)
    finished = await client.post(f"/api/public/invitations/{link}/next")
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "completed"

    # Рекрутеру ушло письмо, задачи обработки поставлены в очередь.
    async with get_session_maker()() as session:
        kinds = sorted(
            (
                await session.scalars(
                    select(Job.kind).where(
                        Job.payload["interview_id"].as_string() == interview["id"]
                    )
                )
            ).all()
        )
        assert "interview.process" in kinds
        assert kinds.count("answer.process") == 2
        email = await session.scalar(
            select(EmailMessage).where(
                EmailMessage.interview_id == uuid.UUID(interview["id"]),
                EmailMessage.kind == "interview.completed",
            )
        )
        assert email is not None and "Иван Кандидат" in email.subject
        server_events = (
            await session.scalars(
                select(InterviewEvent.kind).where(
                    InterviewEvent.interview_id == uuid.UUID(interview["id"])
                )
            )
        ).all()
        assert "question_revealed" in server_events and "question_re_revealed" in server_events
        assert "interview_completed" in server_events

    # Рекрутер видит ответы с подписанными ссылками и события.
    answers = await client.get(f"/api/interviews/{interview['id']}/answers", headers=bearer(token))
    assert answers.status_code == 200
    assert [a["question_index"] for a in answers.json()] == [0, 1]
    assert answers.json()[0]["media_url"].startswith("/api/media/")
    assert answers.json()[0]["question_text"] == "Расскажите о себе"
    video = await client.get(answers.json()[0]["media_url"], headers={"Range": "bytes=0-3"})
    assert video.status_code == 206 and video.content == CHUNK[:4]
    staff_events = await client.get(
        f"/api/interviews/{interview['id']}/events", headers=bearer(token)
    )
    assert any(e["kind"] == "paste" and e["source"] == "client" for e in staff_events.json())

    # Кандидату завершённое интервью больше не доступно для записи.
    assert (
        await client.post(f"/api/public/invitations/{link}/questions/1/reveal")
    ).status_code == 409
    public = (await client.get(f"/api/public/invitations/{link}")).json()
    assert public["status"] == "completed"


async def test_chunk_offset_conflict_reports_actual_size(client: AsyncClient) -> None:
    _, _, link, _ = await _consented(client)
    await client.post(f"/api/public/invitations/{link}/start", json={})
    await client.post(f"/api/public/invitations/{link}/questions/0/reveal")
    created = await client.post(
        f"/api/public/invitations/{link}/questions/0/answers", json={"mime_type": "video/mp4"}
    )
    answer_id = created.json()["answer"]["id"]
    ok = await client.patch(
        f"/api/public/invitations/{link}/answers/{answer_id}/chunks",
        content=CHUNK,
        headers={"Upload-Offset": "0"},
    )
    assert ok.status_code == 200
    # Повтор того же куска (ответ потерялся) — конфликт с фактическим размером.
    repeat = await client.patch(
        f"/api/public/invitations/{link}/answers/{answer_id}/chunks",
        content=CHUNK,
        headers={"Upload-Offset": "0"},
    )
    assert repeat.status_code == 409
    assert repeat.headers["upload-offset"] == str(len(CHUNK))
    missing_header = await client.patch(
        f"/api/public/invitations/{link}/answers/{answer_id}/chunks", content=CHUNK
    )
    assert missing_header.status_code == 422
    wrong_size = await client.post(
        f"/api/public/invitations/{link}/answers/{answer_id}/complete",
        json={"size": len(CHUNK) * 3},
    )
    assert wrong_size.status_code == 409


async def test_retakes_limit_and_final_attempt(client: AsyncClient) -> None:
    _, _, link, _ = await _consented(client)
    await client.post(f"/api/public/invitations/{link}/start", json={})
    await client.post(f"/api/public/invitations/{link}/questions/0/reveal")
    first = await _upload_answer(client, link, 0, chunks=1)
    second = await _upload_answer(client, link, 0, chunks=1)
    assert second["attempt"] == 2
    state = (await client.get(f"/api/public/invitations/{link}/state")).json()
    finals = {a["id"]: a["is_final"] for a in state["answers"]}
    assert finals[first["id"]] is False and finals[second["id"]] is True
    # retakes_allowed = 1 → третья попытка запрещена.
    third = await client.post(
        f"/api/public/invitations/{link}/questions/0/answers", json={"mime_type": "video/webm"}
    )
    assert third.status_code == 409


async def test_next_requires_uploaded_answer(client: AsyncClient) -> None:
    _, _, link, _ = await _consented(client)
    await client.post(f"/api/public/invitations/{link}/start", json={})
    response = await client.post(f"/api/public/invitations/{link}/next")
    assert response.status_code == 409


async def test_hiring_manager_cannot_read_unscoped_answers(client: AsyncClient) -> None:
    from tests.helpers import create_invite, invite_token_from_url

    owner_token, interview, _, _ = await _consented(client)
    invite = await create_invite(
        client, owner_token, role="hiring_manager", vacancy_scope=["other"]
    )
    _, manager = await register(client, invite_token=invite_token_from_url(invite["url"]))
    response = await client.get(
        f"/api/interviews/{interview['id']}/answers", headers=bearer(manager)
    )
    assert response.status_code == 403
