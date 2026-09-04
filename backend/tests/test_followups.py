"""Уточняющие вопросы: подбор материала, генерация блока и прохождение в комнате."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from leonit.candidates.models import Interview, InterviewStatus
from leonit.core.db import get_session_maker
from leonit.core.time import utcnow
from leonit.interviews import followups
from leonit.interviews.models import Answer, AnswerStatus
from tests.helpers import bearer, register
from tests.test_candidates import _invite, _token
from tests.test_interview_room import _consented, _upload_answer

SNAPSHOT = [
    {"index": 0, "id": "q0", "text": "Расскажите о себе", "allows_followup": True},
    {"index": 1, "id": "q1", "text": "Что такое GIL?", "allows_followup": False},
    {"index": 2, "id": "q2", "text": "Как искали медленный запрос?", "allows_followup": True},
]


def _answer(index: int, *, status=AnswerStatus.done, text: str | None = "…", attempt: int = 1):
    return Answer(
        interview_id=uuid.uuid4(),
        question_index=index,
        attempt=attempt,
        is_final=True,
        status=status,
        media_size=0,
        upload_offset=0,
        recording_started_at=utcnow(),
        transcript_text=text,
    )


def test_material_is_taken_only_from_allowed_and_transcribed_answers() -> None:
    answers = [
        _answer(0, text="Пишу на Python пять лет"),
        _answer(1, text="GIL — глобальная блокировка"),  # уточнять не разрешено
        _answer(2, status=AnswerStatus.processing, text=None),  # ещё нет транскрипта
    ]
    material = followups.candidates_for_followup(SNAPSHOT, answers)
    assert [index for index, _, _ in material] == [0]
    assert followups.pending_transcripts(SNAPSHOT, answers) == 1

    # Берётся последняя попытка, а уточняющие ответы материалом не становятся.
    retried = [
        _answer(0, text="Первый дубль", attempt=1),
        _answer(0, text="Второй дубль", attempt=2),
    ]
    (item,) = followups.candidates_for_followup(SNAPSHOT, retried)
    assert item[2] == "Второй дубль"


async def test_generate_builds_snapshot_items_linked_to_parents() -> None:
    answers = [_answer(0, text="Работал с очередями")]
    generated = await followups.generate("Python-разработчик", SNAPSHOT, answers, limit=2)
    assert 1 <= len(generated) <= 2
    for item in generated:
        assert item["followup_of"] == 0
        assert item["kind"] == "video" and item["retakes_allowed"] == 0
        assert item["allows_followup"] is False
        assert item["index"] >= len(SNAPSHOT)
        assert item["text"]

    # Лимит 0 и отсутствие материала дают пустой блок.
    assert await followups.generate("X", SNAPSHOT, answers, limit=0) == []
    assert await followups.generate("X", SNAPSHOT, [], limit=2) == []

    # Материала несколько, а модель назвала несуществующий вопрос — не гадаем.
    two = [_answer(0, text="Про очереди"), _answer(2, text="Про план запроса")]
    assert await followups.generate("X", SNAPSHOT, two, limit=2) == []


async def test_model_failure_does_not_break_the_finale(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*args, **kwargs):
        raise ValueError("модель недоступна")

    monkeypatch.setattr(followups, "complete_structured", broken)
    answers = [_answer(0, text="Что-то рассказал")]
    assert await followups.generate("X", SNAPSHOT, answers, limit=2) == []


# ------------------------------------------------------------------ комната


async def _vacancy_with_followups(client: AsyncClient, token: str) -> dict:
    created = await client.post(
        "/api/vacancies",
        json={"title": "Python-разработчик", "description": "Бэкенд"},
        headers=bearer(token),
    )
    vacancy = created.json()
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={
            # Уточнять разрешено только по первому вопросу.
            "questions": [
                {"text": "Расскажите о себе", "allows_followup": True},
                {"text": "Что такое GIL?", "allows_followup": False},
            ]
        },
        headers=bearer(token),
    )
    patched = await client.patch(
        f"/api/vacancies/{vacancy['id']}",
        json={"settings": {"followups_enabled": True, "followups_max": 1, "prep_seconds": 0}},
        headers=bearer(token),
    )
    assert patched.status_code == 200, patched.text
    published = await client.post(f"/api/vacancies/{vacancy['id']}/publish", headers=bearer(token))
    assert published.status_code == 200, published.text
    return published.json()


async def _run_interview(client: AsyncClient, link: str, indexes: list[int]) -> None:
    for index in indexes:
        await client.post(f"/api/public/invitations/{link}/questions/{index}/reveal")
        await _upload_answer(client, link, index, chunks=1)


async def _transcribe(interview_id: str) -> None:
    async with get_session_maker()() as session:
        await session.execute(
            update(Answer)
            .where(Answer.interview_id == uuid.UUID(interview_id))
            .values(status=AnswerStatus.done, transcript_text="Я делал очереди и профилировал SQL")
        )
        await session.commit()


async def test_followup_block_is_added_before_finish_and_answers_link_to_parent(
    client: AsyncClient,
) -> None:
    _, token = await register(client, organization_name="Napoleon IT")
    vacancy = await _vacancy_with_followups(client, token)
    interview = await _invite(client, token, vacancy["id"], "followup@example.com")
    link = _token(interview["link"])
    page = (await client.get(f"/api/public/invitations/{link}")).json()
    consent = await client.post(
        f"/api/public/invitations/{link}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": "followup@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "document_versions": {d["slug"]: d["version"] for d in page["consent_documents"]},
        },
    )
    assert consent.status_code == 200, consent.text
    assert (await client.post(f"/api/public/invitations/{link}/start", json={})).status_code == 200

    await _run_interview(client, link, [0])
    moved = await client.post(f"/api/public/invitations/{link}/next")
    assert moved.status_code == 200, moved.text
    await _run_interview(client, link, [1])

    # Транскрипты ещё не готовы: комната знает, сколько ждать.
    waiting = await client.get(f"/api/public/invitations/{link}/followups")
    assert waiting.status_code == 200, waiting.text
    assert waiting.json() == {
        "enabled": True,
        "ready": False,
        "pending": 1,
        "wait_seconds": followups.FOLLOWUP_WAIT_S,
    }

    await _transcribe(interview["id"])
    ready = await client.get(f"/api/public/invitations/{link}/followups")
    assert ready.json()["ready"] is True and ready.json()["pending"] == 0

    # «Дальше» после последнего вопроса добавляет блок уточнений, а не финиш.
    state = (await client.post(f"/api/public/invitations/{link}/next")).json()
    assert state["status"] == "in_progress"
    assert state["total_questions"] == 3 and state["current_question_index"] == 2

    followup = next(q for q in state["questions"] if q["index"] == 2)
    assert followup["retakes_allowed"] == 0 and followup["text"]

    await _run_interview(client, link, [2])
    async with get_session_maker()() as session:
        rows = list(
            await session.scalars(
                select(Answer)
                .where(Answer.interview_id == uuid.UUID(interview["id"]))
                .order_by(Answer.question_index)
            )
        )
    child = next(row for row in rows if row.question_index == 2)
    parent = next(row for row in rows if row.question_index == 0)
    assert child.parent_answer_id in {row.id for row in rows if row.parent_answer_id is None}
    assert child.parent_answer_id is not None and parent.parent_answer_id is None

    # Ещё один «дальше» завершает интервью: блок собирается один раз.
    done = (await client.post(f"/api/public/invitations/{link}/next")).json()
    assert done["status"] == "completed"
    async with get_session_maker()() as session:
        row = await session.get(Interview, uuid.UUID(interview["id"]))
        assert row is not None and row.status == InterviewStatus.completed
        assert (row.settings_snapshot or {}).get("followups_done") is True


async def test_finish_without_followups_when_setting_is_off(client: AsyncClient) -> None:
    _, _interview, link, _ = await _consented(client)
    assert (await client.post(f"/api/public/invitations/{link}/start", json={})).status_code == 200
    status = await client.get(f"/api/public/invitations/{link}/followups")
    assert status.json() == {"enabled": False, "ready": True, "pending": 0, "wait_seconds": 0}
    await _run_interview(client, link, [0])
    await client.post(f"/api/public/invitations/{link}/next")
    await _run_interview(client, link, [1])
    finished = (await client.post(f"/api/public/invitations/{link}/next")).json()
    assert finished["status"] == "completed" and finished["total_questions"] == 2
