from __future__ import annotations

from httpx import AsyncClient

from tests.helpers import bearer, create_invite, invite_token_from_url, register

RUBRIC = [
    {
        "id": "python",
        "name": "Python",
        "description": "Язык и стандартная библиотека",
        "weight": 5,
        "levels": {"1": "Путается в базовых конструкциях", "4": "Объясняет внутренности"},
    },
    {"id": "sql", "name": "SQL", "weight": 3, "levels": {}},
]


async def _vacancy(client: AsyncClient, token: str, **overrides) -> dict:
    payload = {"title": "Python-разработчик", "description": "Бэкенд на FastAPI", **overrides}
    response = await client.post("/api/vacancies", json=payload, headers=bearer(token))
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_read_vacancy(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _vacancy(client, token, skills=[" Python", "python", "SQL ", ""])
    assert vacancy["status"] == "draft"
    assert vacancy["skills"] == ["Python", "SQL"]
    assert vacancy["settings"]["prep_seconds"] == 30
    assert vacancy["settings"]["candidate_feedback_mode"] == "after_decision"
    assert vacancy["question_count"] == 0

    listing = await client.get("/api/vacancies", headers=bearer(token))
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [vacancy["id"]]


async def test_interview_mode_defaults_to_live_and_switches_to_push_to_talk(
    client: AsyncClient,
) -> None:
    _, token = await register(client)
    vacancy = await _vacancy(client, token)
    assert vacancy["settings"]["interview_mode"] == "live"
    updated = await client.patch(
        f"/api/vacancies/{vacancy['id']}",
        json={"settings": {"interview_mode": "push_to_talk"}},
        headers=bearer(token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["settings"]["interview_mode"] == "push_to_talk"
    unknown = await client.patch(
        f"/api/vacancies/{vacancy['id']}",
        json={"settings": {"interview_mode": "telepathy"}},
        headers=bearer(token),
    )
    assert unknown.status_code == 422


async def test_update_rubric_settings_and_questions(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _vacancy(client, token)
    updated = await client.patch(
        f"/api/vacancies/{vacancy['id']}",
        json={
            "rubric": RUBRIC,
            "settings": {"prep_seconds": 45, "max_answer_seconds": 240, "followups_enabled": True},
            "level": "middle",
        },
        headers=bearer(token),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert [c["id"] for c in body["rubric"]] == ["python", "sql"]
    assert body["settings"]["prep_seconds"] == 45
    assert body["settings"]["followups_enabled"] is True
    assert body["level"] == "middle"

    questions = await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={
            "questions": [
                {
                    "text": "Расскажите про GIL",
                    "competency_ids": ["python"],
                    "expected_points": ["что такое GIL", " когда мешает ", ""],
                },
                {
                    "text": "Как устроен индекс B-tree?",
                    "competency_ids": ["sql"],
                    "allows_followup": True,
                    "max_answer_seconds": 120,
                },
            ]
        },
        headers=bearer(token),
    )
    assert questions.status_code == 200, questions.text
    body = questions.json()
    assert [q["position"] for q in body["questions"]] == [0, 1]
    assert body["questions"][0]["expected_points"] == ["что такое GIL", "когда мешает"]
    assert body["questions"][1]["max_answer_seconds"] == 120
    assert body["question_count"] == 2

    # Переставляем местами и удаляем один, сохраняя id первого.
    first_id = body["questions"][0]["id"]
    second_id = body["questions"][1]["id"]
    reordered = await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={
            "questions": [
                {"id": second_id, "text": "B-tree?", "competency_ids": ["sql"]},
                {"id": first_id, "text": "GIL?", "competency_ids": ["python"]},
                {"text": "Новый вопрос"},
            ]
        },
        headers=bearer(token),
    )
    assert reordered.status_code == 200, reordered.text
    ids = [q["id"] for q in reordered.json()["questions"]]
    assert ids[:2] == [second_id, first_id]
    assert len(ids) == 3


async def test_questions_reject_unknown_competency(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _vacancy(client, token)
    response = await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={"questions": [{"text": "Вопрос", "competency_ids": ["ghost"]}]},
        headers=bearer(token),
    )
    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]


async def test_removing_competency_detaches_it_from_questions(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _vacancy(client, token)
    await client.patch(
        f"/api/vacancies/{vacancy['id']}", json={"rubric": RUBRIC}, headers=bearer(token)
    )
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={"questions": [{"text": "Вопрос", "competency_ids": ["python", "sql"]}]},
        headers=bearer(token),
    )
    response = await client.patch(
        f"/api/vacancies/{vacancy['id']}", json={"rubric": RUBRIC[:1]}, headers=bearer(token)
    )
    assert response.json()["questions"][0]["competency_ids"] == ["python"]


async def test_publish_requires_questions_and_description(client: AsyncClient) -> None:
    _, token = await register(client)
    empty = await _vacancy(client, token, description="")
    denied = await client.post(f"/api/vacancies/{empty['id']}/publish", headers=bearer(token))
    assert denied.status_code == 422
    assert "нет описания" in denied.json()["detail"]
    assert "нет ни одного вопроса" in denied.json()["detail"]

    vacancy = await _vacancy(client, token)
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={"questions": [{"text": "Вопрос"}]},
        headers=bearer(token),
    )
    published = await client.post(f"/api/vacancies/{vacancy['id']}/publish", headers=bearer(token))
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"]

    draft = await client.post(f"/api/vacancies/{vacancy['id']}/unpublish", headers=bearer(token))
    assert draft.json()["status"] == "draft"


async def test_archive_blocks_edits_and_restore_returns_draft(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _vacancy(client, token)
    archived = await client.post(f"/api/vacancies/{vacancy['id']}/archive", headers=bearer(token))
    assert archived.json()["status"] == "archived"
    edit = await client.patch(
        f"/api/vacancies/{vacancy['id']}", json={"title": "Новое"}, headers=bearer(token)
    )
    assert edit.status_code == 422
    only_archived = await client.get("/api/vacancies?status=archived", headers=bearer(token))
    assert [v["id"] for v in only_archived.json()] == [vacancy["id"]]
    restored = await client.post(f"/api/vacancies/{vacancy['id']}/restore", headers=bearer(token))
    assert restored.json()["status"] == "draft"


async def test_hiring_manager_sees_only_scoped_vacancies(client: AsyncClient) -> None:
    _, owner = await register(client)
    allowed = await _vacancy(client, owner, title="Разрешённая")
    hidden = await _vacancy(client, owner, title="Скрытая")
    invite = await create_invite(
        client, owner, role="hiring_manager", vacancy_scope=[allowed["id"]]
    )
    _, manager = await register(client, invite_token=invite_token_from_url(invite["url"]))

    listing = (await client.get("/api/vacancies", headers=bearer(manager))).json()
    assert [v["id"] for v in listing] == [allowed["id"]]
    assert (
        await client.get(f"/api/vacancies/{hidden['id']}", headers=bearer(manager))
    ).status_code == 403
    assert (
        await client.get(f"/api/vacancies/{allowed['id']}", headers=bearer(manager))
    ).status_code == 200
    forbidden = await client.patch(
        f"/api/vacancies/{allowed['id']}", json={"title": "x"}, headers=bearer(manager)
    )
    assert forbidden.status_code == 403
    create = await client.post("/api/vacancies", json={"title": "x"}, headers=bearer(manager))
    assert create.status_code == 403


async def test_vacancy_of_other_organization_is_not_found(client: AsyncClient) -> None:
    _, owner = await register(client)
    vacancy = await _vacancy(client, owner)
    _, stranger = await register(client, organization_name="Чужая")
    assert (
        await client.get(f"/api/vacancies/{vacancy['id']}", headers=bearer(stranger))
    ).status_code == 404


async def test_rubric_validation(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _vacancy(client, token)
    duplicate = await client.patch(
        f"/api/vacancies/{vacancy['id']}",
        json={"rubric": [RUBRIC[0], RUBRIC[0]]},
        headers=bearer(token),
    )
    assert duplicate.status_code == 422
    bad_level = await client.patch(
        f"/api/vacancies/{vacancy['id']}",
        json={"rubric": [{"id": "x", "name": "X", "levels": {"7": "?"}}]},
        headers=bearer(token),
    )
    assert bad_level.status_code == 422
