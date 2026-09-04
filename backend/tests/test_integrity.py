"""Достоверность записи: правила, пороги против ложных срабатываний, вердикты ревьюера."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from leonit.candidates.models import Interview, InterviewStatus
from leonit.core.db import get_session_maker
from leonit.core.time import utcnow
from leonit.integrity.models import IntegrityReview, IntegrityVerdict
from leonit.integrity.rules import (
    AnswerRow,
    EventRow,
    analyze,
    summary_level,
)
from leonit.integrity.service import integrity_report
from leonit.interviews.models import Answer, AnswerStatus, InterviewEvent
from tests.helpers import bearer, create_invite, invite_token_from_url, register
from tests.test_candidates import _invite, _published_vacancy

BASE = utcnow()


def _event(kind: str, offset_s: float, *, index: int | None = 0, **payload) -> EventRow:
    return EventRow(
        kind=kind,
        at_server=BASE + timedelta(seconds=offset_s),
        question_index=index,
        payload=payload,
    )


def _window(index: int = 0, start: float = 0, end: float = 120) -> list[EventRow]:
    return [
        _event("recorder_started", start, index=index),
        _event("recorder_stopped", end, index=index),
    ]


# ------------------------------------------------------------------ правила


def test_short_focus_loss_is_not_a_flag() -> None:
    events = [
        *_window(),
        _event("window_blur", 10),
        _event("window_focus", 12),  # две секунды — не наблюдение
    ]
    assert analyze(events, []) == []
    assert summary_level([]) == "info"


def test_long_and_repeated_absences_are_flagged() -> None:
    events = [
        *_window(),
        _event("visibility_hidden", 10),
        _event("visibility_visible", 30),  # 20 с — сразу заметно
    ]
    (observation,) = analyze(events, [])
    assert observation.code == "away_during_answer" and observation.level == "attention"
    assert observation.question_index == 0 and observation.evidence["total_ms"] == 20_000

    repeated = [
        *_window(),
        _event("window_blur", 10),
        _event("window_focus", 15),
        _event("window_blur", 40),
        _event("window_focus", 45),
    ]
    (repeat,) = analyze(repeated, [])
    assert repeat.code == "away_during_answer" and repeat.evidence["count"] == 2


def test_absence_between_questions_is_ignored() -> None:
    events = [
        *_window(index=0, start=0, end=60),
        # Ушёл после записи первого ответа и до начала второго.
        _event("visibility_hidden", 70, index=0),
        _event("visibility_visible", 200, index=0),
    ]
    assert analyze(events, []) == []


def test_unfinished_absence_counts_until_recording_ends() -> None:
    events = [*_window(index=0, start=0, end=60), _event("visibility_hidden", 20)]
    (observation,) = analyze(events, [])
    assert observation.evidence["total_ms"] == 40_000


def test_paste_is_flagged_only_when_long() -> None:
    small = [*_window(), _event("paste", 20, length=5)]
    assert analyze(small, []) == []
    big = [*_window(), _event("paste", 20, length=500)]
    (observation,) = analyze(big, [])
    assert observation.code == "paste_during_answer" and observation.evidence["chars"] == 500


def test_virtual_camera_is_a_risk() -> None:
    events = [
        *_window(),
        _event(
            "devices_enumerated",
            1,
            index=None,
            devices=[{"label": "OBS Virtual Camera"}, {"label": "FaceTime HD"}],
        ),
    ]
    observations = analyze(events, [])
    codes = {item.code for item in observations}
    assert "virtual_camera" in codes
    assert summary_level(observations) == "risk"


def test_foreign_recorder_and_duration_mismatch() -> None:
    answers = [
        AnswerRow(
            question_index=0,
            duration_ms=60_000,
            client_duration_ms=60_500,
            media_meta={"tags": {"format.encoder": "Lavf60.16.100"}},
        ),
        AnswerRow(
            question_index=1,
            duration_ms=20_000,
            client_duration_ms=90_000,
            media_meta={"tags": {"format.encoder": "Chrome"}},
        ),
    ]
    observations = analyze([], answers)
    codes = {item.code for item in observations}
    assert codes == {"foreign_recorder", "duration_mismatch"}
    assert summary_level(observations) == "risk"

    # Браузерная подпись рядом с Lavf (Chrome пишет через libav) — не флаг.
    mixed = [
        AnswerRow(
            question_index=0,
            duration_ms=60_000,
            client_duration_ms=61_000,
            media_meta={"tags": {"format.encoder": "Lavf", "video.handler_name": "Chrome"}},
        )
    ]
    assert analyze([], mixed) == []


def test_faces_rules_need_several_samples() -> None:
    single = [*_window(), _event("faces", 10, count=2)]
    assert analyze(single, []) == []
    many = [*_window(), _event("faces", 10, count=2), _event("faces", 20, count=2)]
    (observation,) = analyze(many, [])
    assert observation.code == "multiple_faces"

    empty = [
        *_window(),
        _event("faces", 10, count=0),
        _event("faces", 20, count=0),
        _event("faces", 30, count=1),
    ]
    (observation,) = analyze(empty, [])
    assert observation.code == "no_face" and observation.evidence["without_face"] == 2


def test_heartbeat_gap_is_a_fact_not_a_flag() -> None:
    events = [*_window(index=0, start=0, end=60), _event("heartbeat", 5), _event("heartbeat", 55)]
    (observation,) = analyze(events, [])
    assert observation.code == "heartbeat_gap" and observation.level == "info"
    assert summary_level([observation]) == "info"
    # Без хартбита вовсе (телеметрия выключена) факта нет — молчим, а не пугаем.
    assert analyze(_window(index=0, start=0, end=600), []) == []


# --------------------------------------------------------------------- API


async def _interview_with_signals(client: AsyncClient) -> tuple[str, dict, dict]:
    """Интервью с событиями и ответом, дающими одно наблюдение и один факт."""
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "risky@example.com")
    now = utcnow()
    async with get_session_maker()() as session:
        answer = Answer(
            interview_id=uuid.UUID(interview["id"]),
            question_index=0,
            attempt=1,
            is_final=True,
            status=AnswerStatus.done,
            media_size=1024,
            upload_offset=1024,
            recording_started_at=now,
            duration_ms=60_000,
            client_duration_ms=60_000,
            chunk_count=1,
            media_meta={"tags": {"format.encoder": "Lavf60"}},
        )
        session.add(answer)
        for kind, offset, payload in (
            ("recorder_started", 0, {}),
            ("visibility_hidden", 10, {}),
            ("visibility_visible", 40, {}),
            ("recorder_stopped", 60, {}),
        ):
            session.add(
                InterviewEvent(
                    interview_id=uuid.UUID(interview["id"]),
                    question_index=0,
                    kind=kind,
                    source="client",
                    at_server=now + timedelta(seconds=offset),
                    payload=payload,
                )
            )
        await session.commit()
    return token, interview, vacancy


async def test_integrity_endpoint_reports_and_review_changes_level(client: AsyncClient) -> None:
    token, interview, _ = await _interview_with_signals(client)
    response = await client.get(
        f"/api/interviews/{interview['id']}/integrity", headers=bearer(token)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["level"] == "risk" and body["flags"] == 2
    codes = {item["code"] for item in body["observations"]}
    assert codes == {"foreign_recorder", "away_during_answer"}
    assert all(item["review"] is None for item in body["observations"])

    # Ревьюер объясняет: это была запись через виртуальную камеру для теста.
    reviewed = await client.post(
        f"/api/interviews/{interview['id']}/integrity/review",
        json={
            "code": "foreign_recorder",
            "question_index": 0,
            "verdict": "false_positive",
            "comment": "Проверяли на тестовом стенде",
        },
        headers=bearer(token),
    )
    assert reviewed.status_code == 200, reviewed.text
    after = reviewed.json()
    assert after["level"] == "attention" and after["flags"] == 1
    marked = next(item for item in after["observations"] if item["code"] == "foreign_recorder")
    assert marked["review"]["verdict"] == "false_positive"
    assert marked["review"]["comment"] == "Проверяли на тестовом стенде"

    # Повторное решение по тому же наблюдению обновляет вердикт, а не плодит записи.
    again = await client.post(
        f"/api/interviews/{interview['id']}/integrity/review",
        json={"code": "foreign_recorder", "question_index": 0, "verdict": "confirmed"},
        headers=bearer(token),
    )
    assert again.status_code == 200 and again.json()["level"] == "risk"
    async with get_session_maker()() as session:
        rows = list(
            await session.scalars(
                select(IntegrityReview).where(
                    IntegrityReview.interview_id == uuid.UUID(interview["id"])
                )
            )
        )
    assert len(rows) == 1 and rows[0].verdict == IntegrityVerdict.confirmed

    # Наблюдения, которого нет, отметить нельзя.
    missing = await client.post(
        f"/api/interviews/{interview['id']}/integrity/review",
        json={"code": "multiple_faces", "question_index": 0, "verdict": "confirmed"},
        headers=bearer(token),
    )
    assert missing.status_code == 404


async def test_integrity_respects_roles_and_scope(client: AsyncClient) -> None:
    token, interview, vacancy = await _interview_with_signals(client)
    other = await _published_vacancy(client, token, "Другая вакансия")
    invite = await create_invite(client, token, role="hiring_manager", vacancy_scope=[other["id"]])
    _, manager = await register(client, invite_token=invite_token_from_url(invite["url"]))
    denied = await client.get(
        f"/api/interviews/{interview['id']}/integrity", headers=bearer(manager)
    )
    assert denied.status_code in (403, 404)

    allowed_invite = await create_invite(
        client, token, role="hiring_manager", vacancy_scope=[vacancy["id"]]
    )
    _, allowed = await register(client, invite_token=invite_token_from_url(allowed_invite["url"]))
    visible = await client.get(
        f"/api/interviews/{interview['id']}/integrity", headers=bearer(allowed)
    )
    assert visible.status_code == 200 and visible.json()["flags"] == 2


async def test_public_report_hides_integrity_unless_enabled(client: AsyncClient) -> None:
    token, interview, _ = await _interview_with_signals(client)
    async with get_session_maker()() as session:
        row = await session.get(Interview, uuid.UUID(interview["id"]))
        assert row is not None
    quiet = await client.post(
        f"/api/interviews/{interview['id']}/shares",
        json={"label": "без деталей", "expires_in_days": 7},
        headers=bearer(token),
    )
    assert quiet.status_code == 201, quiet.text
    quiet_token = quiet.json()["url"].rsplit("/", 1)[-1]
    report = await client.get(f"/api/public/reports/{quiet_token}")
    assert report.status_code == 200 and report.json()["integrity"] is None

    full = await client.post(
        f"/api/interviews/{interview['id']}/shares",
        json={"label": "с деталями", "expires_in_days": 7, "include_integrity": True},
        headers=bearer(token),
    )
    full_token = full.json()["url"].rsplit("/", 1)[-1]
    detailed = await client.get(f"/api/public/reports/{full_token}")
    assert detailed.status_code == 200
    assert detailed.json()["integrity"]["level"] == "risk"


async def test_integrity_report_is_empty_without_signals(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "quiet@example.com")
    async with get_session_maker()() as session:
        report = await integrity_report(session, uuid.UUID(interview["id"]))
    assert report == {
        "level": "info",
        "level_label": "без замечаний",
        "observations": [],
        "checked": False,
        "flags": 0,
    }


@pytest.mark.parametrize("verdict", ["confirmed", "false_positive"])
async def test_review_verdicts_are_validated(client: AsyncClient, verdict: str) -> None:
    token, interview, _ = await _interview_with_signals(client)
    ok = await client.post(
        f"/api/interviews/{interview['id']}/integrity/review",
        json={"code": "away_during_answer", "question_index": 0, "verdict": verdict},
        headers=bearer(token),
    )
    assert ok.status_code == 200
    bad = await client.post(
        f"/api/interviews/{interview['id']}/integrity/review",
        json={"code": "away_during_answer", "question_index": 0, "verdict": "maybe"},
        headers=bearer(token),
    )
    assert bad.status_code == 422


async def test_dashboard_counts_flagged_interviews(client: AsyncClient) -> None:
    """Доля флагов на дашборде считается по реальным наблюдениям."""
    token, interview, _ = await _interview_with_signals(client)
    async with get_session_maker()() as session:
        await session.execute(
            update(Interview)
            .where(Interview.id == uuid.UUID(interview["id"]))
            .values(completed_at=utcnow(), status=InterviewStatus.completed)
        )
        await session.commit()

    overview = await client.get("/api/dashboard/overview", headers=bearer(token))
    assert overview.status_code == 200, overview.text
    assert overview.json()["flags_rate"] == 1.0

    # Ревьюер снял оба наблюдения — доля падает до нуля.
    for code in ("foreign_recorder", "away_during_answer"):
        marked = await client.post(
            f"/api/interviews/{interview['id']}/integrity/review",
            json={"code": code, "question_index": 0, "verdict": "false_positive"},
            headers=bearer(token),
        )
        assert marked.status_code == 200, marked.text
    cleared = await client.get("/api/dashboard/overview", headers=bearer(token))
    assert cleared.json()["flags_rate"] == 0.0
