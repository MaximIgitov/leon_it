from __future__ import annotations

from httpx import AsyncClient

from tests.helpers import bearer, create_invite, invite_token_from_url, register
from tests.test_interview_room import _consented, _upload_answer


async def _completed_interview(client: AsyncClient) -> tuple[str, dict, str]:
    token, interview, link, _ = await _consented(client)
    await client.post(f"/api/public/invitations/{link}/start", json={})
    for index in range(2):
        await client.post(f"/api/public/invitations/{link}/questions/{index}/reveal")
        await _upload_answer(client, link, index, chunks=1)
        await client.post(f"/api/public/invitations/{link}/next")
    return token, interview, link


async def test_decision_notes_and_share_flow(client: AsyncClient) -> None:
    token, interview, _ = await _completed_interview(client)

    decided = await client.post(
        f"/api/interviews/{interview['id']}/decision",
        json={"decision": "hold", "note": "Нужен второй взгляд"},
        headers=bearer(token),
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["decision"] == "hold"

    note = await client.post(
        f"/api/interviews/{interview['id']}/notes",
        json={"text": "Хорошо объясняет GIL", "at_s": 12.5},
        headers=bearer(token),
    )
    assert note.status_code == 201
    notes = (
        await client.get(f"/api/interviews/{interview['id']}/notes", headers=bearer(token))
    ).json()
    assert [n["text"] for n in notes] == ["Хорошо объясняет GIL"]
    assert notes[0]["at_s"] == 12.5

    share = await client.post(
        f"/api/interviews/{interview['id']}/shares",
        json={"label": "Тимлид Петров", "expires_in_days": 7},
        headers=bearer(token),
    )
    assert share.status_code == 201, share.text
    body = share.json()
    assert body["status"] == "active" and body["url"].count("/r/") == 1
    share_token = body["url"].rsplit("/r/", 1)[1]

    listed = (
        await client.get(f"/api/interviews/{interview['id']}/shares", headers=bearer(token))
    ).json()
    assert listed[0]["url"] is None and listed[0]["view_count"] == 0

    report = await client.get(
        f"/api/public/reports/{share_token}", headers={"User-Agent": "ua-test"}
    )
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["candidate_name"] == "Иван Кандидат"
    assert data["vacancy_title"] == "Python-разработчик"
    assert len(data["answers"]) == 2
    assert data["answers"][0]["media_url"].startswith("/api/media/")
    assert data["answers"][0]["question_text"] == "Расскажите о себе"
    assert data["integrity"] is None
    assert [n["text"] for n in data["notes"]] == ["Хорошо объясняет GIL"]

    guest_note = await client.post(
        f"/api/public/reports/{share_token}/notes", json={"text": "Согласен"}
    )
    assert guest_note.status_code == 201
    assert guest_note.json()["author_label"] == "Тимлид Петров"

    guest_decision = await client.post(
        f"/api/public/reports/{share_token}/decision", json={"decision": "advance"}
    )
    assert guest_decision.status_code == 204
    updated = (await client.get(f"/api/interviews/{interview['id']}", headers=bearer(token))).json()
    assert updated["decision"] == "advance"

    views = (
        await client.get(f"/api/interviews/{interview['id']}/shares/views", headers=bearer(token))
    ).json()
    assert {v["what"] for v in views} == {"report", "decision"}
    assert any(v["user_agent"] == "ua-test" for v in views)
    listed = (
        await client.get(f"/api/interviews/{interview['id']}/shares", headers=bearer(token))
    ).json()
    assert listed[0]["view_count"] == 1

    revoked = await client.delete(
        f"/api/interviews/{interview['id']}/shares/{body['id']}", headers=bearer(token)
    )
    assert revoked.json()["status"] == "revoked"
    assert (await client.get(f"/api/public/reports/{share_token}")).status_code == 403

    extended = await client.post(
        f"/api/interviews/{interview['id']}/shares/{body['id']}/extend?days=30",
        headers=bearer(token),
    )
    assert extended.json()["status"] == "active"
    assert (await client.get(f"/api/public/reports/{share_token}")).status_code == 200


async def test_decision_requires_completed_interview(client: AsyncClient) -> None:
    token, interview, _, _ = await _consented(client)
    response = await client.post(
        f"/api/interviews/{interview['id']}/decision",
        json={"decision": "advance"},
        headers=bearer(token),
    )
    assert response.status_code == 409


async def test_hiring_manager_can_decide_only_in_scope(client: AsyncClient) -> None:
    owner, interview, _ = await _completed_interview(client)
    invite = await create_invite(
        client, owner, role="hiring_manager", vacancy_scope=[interview["vacancy_id"]]
    )
    _, manager = await register(client, invite_token=invite_token_from_url(invite["url"]))
    ok = await client.post(
        f"/api/interviews/{interview['id']}/decision",
        json={"decision": "reject", "note": "Не хватает опыта"},
        headers=bearer(manager),
    )
    assert ok.status_code == 200
    # До заключения модели решение фиксируется, но статус обработки не меняется.
    assert ok.json()["decision"] == "reject"
    assert ok.json()["status"] == "completed"
    cannot_share = await client.post(
        f"/api/interviews/{interview['id']}/shares", json={}, headers=bearer(manager)
    )
    assert cannot_share.status_code == 403


async def test_unknown_share_token(client: AsyncClient) -> None:
    assert (await client.get("/api/public/reports/nope")).status_code == 404
