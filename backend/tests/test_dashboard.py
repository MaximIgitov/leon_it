"""Дашборд: воронка, сроки, разбивки, согласие с ИИ, доверие к цитатам, периметр и период.

Заключения — настоящие строки ``evaluations``: один сценарий гоняет конвейер
оценки целиком (комната → транскрипты → ``interview.process`` с фейковым
провайдером → «Переобработать»), остальные вставляют строки напрямую.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from leonit.candidates.models import Interview
from leonit.core.db import get_session_maker
from leonit.core.time import utcnow
from leonit.evaluation.jobs import process_interview
from leonit.evaluation.models import Evaluation, EvaluationStatus
from leonit.evaluation.prompts import PROMPT_VERSION
from tests.helpers import bearer, create_invite, invite_token_from_url, register
from tests.test_candidates import _invite, _published_vacancy, _token
from tests.test_evaluation import (
    _completed_interview,
    _ctx,
    _finish_answers,
    _job_by_key,
    _settle_jobs,
)
from tests.test_interview_room import _upload_answer

# ------------------------------------------------------------------ helpers


async def _consent(client: AsyncClient, link: str, email: str) -> None:
    page = (await client.get(f"/api/public/invitations/{link}")).json()
    response = await client.post(
        f"/api/public/invitations/{link}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": email,
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "document_versions": {d["slug"]: d["version"] for d in page["consent_documents"]},
        },
    )
    assert response.status_code == 200, response.text


async def _complete(client: AsyncClient, link: str, *, retake_first: bool = False) -> None:
    assert (await client.post(f"/api/public/invitations/{link}/start", json={})).status_code == 200
    for index in range(2):
        await client.post(f"/api/public/invitations/{link}/questions/{index}/reveal")
        await _upload_answer(client, link, index, chunks=1)
        if index == 0 and retake_first:
            await _upload_answer(client, link, index, chunks=1)
        finished = await client.post(f"/api/public/invitations/{link}/next")
        assert finished.status_code == 200, finished.text


async def _invite_many(
    client: AsyncClient, token: str, vacancy_id: str, emails: list[str]
) -> dict[str, dict]:
    return {email: await _invite(client, token, vacancy_id, email) for email in emails}


async def _set_interview(interview_id: str, **values: Any) -> None:
    async with get_session_maker()() as session:
        await session.execute(
            update(Interview).where(Interview.id == uuid.UUID(interview_id)).values(**values)
        )
        await session.commit()


def _evaluation(
    interview_id: str,
    *,
    fit_score: float | None = None,
    recommendation: str | None = None,
    quotes: tuple[int, int] | None = None,
    status: EvaluationStatus = EvaluationStatus.done,
) -> Evaluation:
    return Evaluation(
        interview_id=uuid.UUID(interview_id),
        status=status,
        fit_score=fit_score,
        recommendation=recommendation,
        quotes_found=quotes[0] if quotes else None,
        quotes_total=quotes[1] if quotes else None,
        prompt_version=PROMPT_VERSION,
        model="test",
        evaluated_at=utcnow() if status == EvaluationStatus.done else None,
    )


async def _add_evaluation(interview_id: str, **fields: Any) -> None:
    async with get_session_maker()() as session:
        session.add(_evaluation(interview_id, **fields))
        await session.commit()


async def _decide(client: AsyncClient, token: str, interview_id: str, decision: str) -> None:
    response = await client.post(
        f"/api/interviews/{interview_id}/decision",
        json={"decision": decision},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text


async def _overview(client: AsyncClient, token: str, **params: Any) -> dict:
    response = await client.get("/api/dashboard/overview", params=params, headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


def _step(overview: dict, key: str) -> dict:
    return next(step for step in overview["funnel"] if step["key"] == key)


# -------------------------------------------------------------------- tests


async def test_overview_funnel_breakdowns_agreement_and_quotes(client: AsyncClient) -> None:
    _, token = await register(client, organization_name="Example IT")
    vacancy = await _published_vacancy(client, token)
    emails = [f"{name}@example.com" for name in "abcdefg"]
    interviews = await _invite_many(client, token, vacancy["id"], emails)
    links = {email: _token(interviews[email]["link"]) for email in emails}

    # a, e, f, g доходят до конца; b — только согласие; c — открыл ссылку; d — ничего.
    for email in ("a", "b", "e", "f", "g"):
        await _consent(client, links[f"{email}@example.com"], f"{email}@example.com")
    await client.get(f"/api/public/invitations/{links['c@example.com']}")
    await _complete(client, links["a@example.com"], retake_first=True)
    for email in ("e", "f", "g"):
        await _complete(client, links[f"{email}@example.com"])

    # Решения до заключения: a — «дальше», e — «отказ», f — «пауза», g ждёт.
    await _decide(client, token, interviews["a@example.com"]["id"], "advance")
    await _decide(client, token, interviews["e@example.com"]["id"], "reject")
    await _decide(client, token, interviews["f@example.com"]["id"], "hold")

    # Заключения модели: a совпало (fit ↔ advance), e разошлось (fit ↔ reject),
    # f не считается (hold). Время до результата: 2, 4 и 6 часов → медиана 4.
    # Цитаты: у a и f подтверждены все, у e — одна из двух.
    for email, hours, score, recommendation, quotes in (
        ("a", 2, 82.0, "fit", (3, 3)),
        ("e", 4, 70.0, "fit", (1, 2)),
        ("f", 6, 35.0, "no_fit", (2, 2)),
    ):
        interview = interviews[f"{email}@example.com"]
        current = (
            await client.get(f"/api/interviews/{interview['id']}", headers=bearer(token))
        ).json()
        completed_at = datetime.fromisoformat(current["completed_at"])
        await _set_interview(interview["id"], evaluated_at=completed_at + timedelta(hours=hours))
        await _add_evaluation(
            interview["id"], fit_score=score, recommendation=recommendation, quotes=quotes
        )
    # У g оценка ещё идёт: строка есть, но баллов нет — в метрики не попадает.
    await _add_evaluation(interviews["g@example.com"]["id"], status=EvaluationStatus.pending)

    overview = await _overview(client, token)

    assert [step["count"] for step in overview["funnel"]] == [7, 6, 5, 4, 4, 3, 3]
    assert [step["key"] for step in overview["funnel"]] == [
        "invited",
        "opened",
        "consented",
        "started",
        "completed",
        "evaluated",
        "decided",
    ]
    assert _step(overview, "invited")["rate_from_previous"] is None
    assert _step(overview, "opened")["rate_from_previous"] == pytest.approx(6 / 7, abs=1e-3)
    assert _step(overview, "completed")["rate_from_invited"] == pytest.approx(4 / 7, abs=1e-3)
    assert _step(overview, "evaluated")["rate_from_previous"] == pytest.approx(0.75)

    assert overview["invited"] == 7
    assert overview["completed"] == 4
    assert overview["evaluated"] == 3
    assert overview["decided"] == 3
    assert overview["awaiting_decision"] == 1
    assert overview["completion_rate"] == pytest.approx(4 / 7, abs=1e-3)
    assert overview["active_vacancies"] == 1
    assert overview["interviews_last_7d"] == 7
    assert overview["interviews_last_30d"] == 7
    assert overview["flags_rate"] == 0
    assert overview["vacancy"] is None
    assert overview["period"]["all_time"] is False
    assert overview["period"]["from"] is not None

    assert overview["decision_breakdown"] == {"advance": 1, "reject": 1, "hold": 1, "pending": 1}
    assert overview["recommendation_breakdown"] == {"fit": 2, "no_fit": 1, "needs_check": 0}
    assert overview["avg_fit_score"] == pytest.approx((82 + 70 + 35) / 3, abs=0.1)
    assert overview["ai_agreement"] == pytest.approx(0.5)
    assert overview["ai_agreement_pairs"] == 2
    # Доверие к заключению: у двух из трёх все цитаты подтверждены.
    assert overview["quote_verification_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert overview["unverified_quotes_evaluations"] == 1

    # Интервью проходятся за секунды, заключения — через заданные часы.
    assert 0 <= overview["median_time_to_complete_h"] < 1
    assert overview["median_time_to_result_h"] == pytest.approx(4.0)
    # Одна перезапись на восемь зачётных ответов.
    assert overview["avg_retakes"] == pytest.approx(1 / 8, abs=0.01)


async def test_overview_follows_real_evaluation_pipeline(client: AsyncClient) -> None:
    """Конвейер оценки целиком: транскрипты → задача → заключение → переобработка."""
    token, interview, _, _ = await _completed_interview(client)
    interview_id = interview["id"]

    # Транскриптов ещё нет: интервью завершено, заключения нет.
    before = await _overview(client, token)
    assert before["completed"] == 1 and before["evaluated"] == 0
    assert before["avg_fit_score"] is None and before["quote_verification_rate"] is None
    assert before["recommendation_breakdown"] == {"fit": 0, "no_fit": 0, "needs_check": 0}

    await _finish_answers(interview_id)
    done = await process_interview({"interview_id": interview_id}, _ctx())
    assert done["status"] == "done"

    # Фейковая модель ставит 2 по каждой компетенции (33.3 → no_fit) и придумывает
    # цитаты, которых нет в транскрипте, — заключение с неподтверждёнными цитатами.
    evaluated = await _overview(client, token)
    assert evaluated["evaluated"] == 1 and _step(evaluated, "evaluated")["count"] == 1
    assert evaluated["avg_fit_score"] == pytest.approx(33.3)
    assert evaluated["recommendation_breakdown"] == {"fit": 0, "no_fit": 1, "needs_check": 0}
    assert evaluated["quote_verification_rate"] == 0
    assert evaluated["unverified_quotes_evaluations"] == 1
    assert 0 <= evaluated["median_time_to_result_h"] < 1
    assert evaluated["ai_agreement"] is None and evaluated["ai_agreement_pairs"] == 0

    # «Переобработать» обнуляет заключение: строка остаётся (та же, вторая не
    # появляется), но в метриках её нет, пока новая оценка не готова.
    await _settle_jobs(interview_id)
    accepted = await client.post(f"/api/interviews/{interview_id}/reprocess", headers=bearer(token))
    assert accepted.status_code == 202, accepted.text
    reset = await _overview(client, token)
    assert reset["completed"] == 1 and reset["evaluated"] == 0
    assert reset["avg_fit_score"] is None
    assert reset["recommendation_breakdown"] == {"fit": 0, "no_fit": 0, "needs_check": 0}
    assert reset["quote_verification_rate"] is None
    assert reset["unverified_quotes_evaluations"] == 0
    assert reset["median_time_to_result_h"] is None

    # Задача переобработки доводит оценку до конца — метрики возвращаются.
    job = await _job_by_key(f"interview:{interview_id}:reprocess:1")
    assert job is not None
    redone = await process_interview(job.payload, _ctx())
    assert redone["status"] == "done"
    again = await _overview(client, token)
    assert again["evaluated"] == 1 and again["avg_fit_score"] == pytest.approx(33.3)
    assert again["unverified_quotes_evaluations"] == 1

    # Решение «отказ» совпадает с рекомендацией no_fit.
    await _decide(client, token, interview_id, "reject")
    decided = await _overview(client, token)
    assert decided["ai_agreement"] == pytest.approx(1.0) and decided["ai_agreement_pairs"] == 1
    assert decided["decision_breakdown"] == {"advance": 0, "reject": 1, "hold": 0, "pending": 0}


async def test_overview_without_evaluations(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    await _invite(client, token, vacancy["id"], "solo@example.com")

    overview = await _overview(client, token)
    assert overview["avg_fit_score"] is None
    assert overview["ai_agreement"] is None
    assert overview["ai_agreement_pairs"] == 0
    assert overview["quote_verification_rate"] is None
    assert overview["unverified_quotes_evaluations"] == 0
    assert overview["recommendation_breakdown"] == {"fit": 0, "no_fit": 0, "needs_check": 0}
    assert overview["invited"] == 1
    assert overview["completion_rate"] == 0
    assert overview["median_time_to_complete_h"] is None
    assert overview["avg_retakes"] is None


async def test_quote_verification_ignores_evaluations_without_quotes(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interviews = await _invite_many(
        client, token, vacancy["id"], ["q1@example.com", "q2@example.com", "q3@example.com"]
    )
    # Без цитат проверять нечего: такое заключение не участвует в доле.
    await _add_evaluation(
        interviews["q1@example.com"]["id"], fit_score=50.0, recommendation="needs_check"
    )
    await _add_evaluation(
        interviews["q2@example.com"]["id"],
        fit_score=50.0,
        recommendation="needs_check",
        quotes=(0, 0),
    )
    only_no_quotes = await _overview(client, token)
    assert only_no_quotes["quote_verification_rate"] is None
    assert only_no_quotes["unverified_quotes_evaluations"] == 0
    assert only_no_quotes["recommendation_breakdown"]["needs_check"] == 2

    await _add_evaluation(
        interviews["q3@example.com"]["id"], fit_score=80.0, recommendation="fit", quotes=(0, 4)
    )
    with_unverified = await _overview(client, token)
    assert with_unverified["quote_verification_rate"] == 0
    assert with_unverified["unverified_quotes_evaluations"] == 1


async def test_single_evaluation_per_interview(client: AsyncClient) -> None:
    """Второе заключение на то же интервью невозможно — ``interview_id`` уникален."""
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "one@example.com")
    await _add_evaluation(interview["id"], fit_score=90.0, recommendation="fit", quotes=(2, 2))

    async with get_session_maker()() as session:
        session.add(_evaluation(interview["id"], fit_score=10.0, recommendation="no_fit"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    overview = await _overview(client, token)
    assert overview["recommendation_breakdown"] == {"fit": 1, "no_fit": 0, "needs_check": 0}
    assert overview["avg_fit_score"] == pytest.approx(90.0)


async def test_vacancy_dashboard_and_hiring_manager_scope(client: AsyncClient) -> None:
    _, owner = await register(client)
    first = await _published_vacancy(client, owner, title="Python-разработчик")
    second = await _published_vacancy(client, owner, title="Аналитик")
    await _invite_many(client, owner, first["id"], ["p1@example.com", "p2@example.com"])
    await _invite_many(client, owner, second["id"], ["an@example.com"])

    total = (await client.get("/api/dashboard/overview", headers=bearer(owner))).json()
    assert total["invited"] == 3
    assert total["active_vacancies"] == 2

    per_vacancy = await client.get(
        f"/api/dashboard/vacancies/{second['id']}", headers=bearer(owner)
    )
    assert per_vacancy.status_code == 200, per_vacancy.text
    assert per_vacancy.json()["invited"] == 1
    assert per_vacancy.json()["vacancy"] == {
        "id": second["id"],
        "title": "Аналитик",
        "status": "published",
    }
    assert per_vacancy.json()["active_vacancies"] == 1

    unknown = await client.get(f"/api/dashboard/vacancies/{uuid.uuid4()}", headers=bearer(owner))
    assert unknown.status_code == 404

    # Нанимающий менеджер допущен только к первой вакансии.
    invite = await create_invite(client, owner, role="hiring_manager", vacancy_scope=[first["id"]])
    _, manager = await register(client, invite_token=invite_token_from_url(invite["url"]))
    scoped = (await client.get("/api/dashboard/overview", headers=bearer(manager))).json()
    assert scoped["invited"] == 2
    assert scoped["active_vacancies"] == 1
    assert (
        await client.get(f"/api/dashboard/vacancies/{first['id']}", headers=bearer(manager))
    ).status_code == 200
    assert (
        await client.get(f"/api/dashboard/vacancies/{second['id']}", headers=bearer(manager))
    ).status_code == 403
    assert (
        await client.get(
            f"/api/dashboard/timeseries?vacancy_id={second['id']}", headers=bearer(manager)
        )
    ).status_code == 403

    # Мусор в периметре не роняет запрос, а просто ничего не открывает.
    junk = await create_invite(client, owner, role="hiring_manager", vacancy_scope=["other"])
    _, outsider = await register(client, invite_token=invite_token_from_url(junk["url"]))
    empty = (await client.get("/api/dashboard/overview", headers=bearer(outsider))).json()
    assert empty["invited"] == 0 and empty["active_vacancies"] == 0

    # Чужая организация ничего не видит.
    _, stranger = await register(client, organization_name="Другая")
    assert (await client.get("/api/dashboard/overview", headers=bearer(stranger))).json()[
        "invited"
    ] == 0
    assert (
        await client.get(f"/api/dashboard/vacancies/{first['id']}", headers=bearer(stranger))
    ).status_code == 404


async def test_period_bounds(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interviews = await _invite_many(
        client, token, vacancy["id"], ["old@example.com", "new@example.com"]
    )
    sixty_days_ago = utcnow() - timedelta(days=60)
    await _set_interview(interviews["old@example.com"]["id"], invited_at=sixty_days_ago)

    default = (await client.get("/api/dashboard/overview", headers=bearer(token))).json()
    assert default["invited"] == 1
    assert default["period"]["all_time"] is False
    # Старое интервью не входит в период, но «пульс» за 30 дней его тоже не видит.
    assert default["interviews_last_30d"] == 1

    everything = (
        await client.get("/api/dashboard/overview?all_time=true", headers=bearer(token))
    ).json()
    assert everything["invited"] == 2
    assert everything["period"]["all_time"] is True
    assert everything["period"]["from"] is None
    assert everything["interviews_last_30d"] == 1

    start = (utcnow() - timedelta(days=70)).isoformat()
    end = (utcnow() - timedelta(days=50)).isoformat()
    window = (
        await client.get(
            "/api/dashboard/overview", params={"from": start, "to": end}, headers=bearer(token)
        )
    ).json()
    assert window["invited"] == 1
    assert datetime.fromisoformat(window["period"]["to"]) == datetime.fromisoformat(end)

    # Дата без зоны трактуется как UTC и не ломает запрос.
    naive = await client.get(
        "/api/dashboard/overview",
        params={"from": (utcnow() - timedelta(days=90)).replace(tzinfo=None).isoformat()},
        headers=bearer(token),
    )
    assert naive.status_code == 200 and naive.json()["invited"] == 2

    inverted = await client.get(
        "/api/dashboard/overview",
        params={"from": utcnow().isoformat(), "to": (utcnow() - timedelta(days=1)).isoformat()},
        headers=bearer(token),
    )
    assert inverted.status_code == 422

    # Крайние даты: раньше 2000 года и дальше года вперёд отвергаются, а не
    # роняют арифметику по дням в 500 (OverflowError).
    for params in (
        {"from": "0001-01-01T00:00:00", "tz_offset_minutes": -600},
        {"to": "9999-12-31T23:59:59", "tz_offset_minutes": 720},
    ):
        for path in ("/api/dashboard/overview", "/api/dashboard/timeseries"):
            response = await client.get(path, params=params, headers=bearer(token))
            assert response.status_code == 422, (path, params, response.text)


async def test_timeseries_by_day(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interviews = await _invite_many(
        client, token, vacancy["id"], ["t1@example.com", "t2@example.com", "t3@example.com"]
    )
    link = _token(interviews["t1@example.com"]["link"])
    await _consent(client, link, "t1@example.com")
    await _complete(client, link)
    # Третьего пригласили неделю назад — он попадает в свой день, а не в сегодняшний.
    await _set_interview(
        interviews["t3@example.com"]["id"], invited_at=utcnow() - timedelta(days=7)
    )

    response = await client.get(
        "/api/dashboard/timeseries", params={"tz_offset_minutes": 180}, headers=bearer(token)
    )
    assert response.status_code == 200, response.text
    series = response.json()
    assert series["vacancy_id"] is None
    # 30 дней назад … сегодня включительно — 31 точка, дни без событий заполнены нулями.
    assert len(series["points"]) == 31
    assert series["points"][-1]["invited"] == 2
    assert series["points"][-1]["completed"] == 1
    assert series["points"][-1]["evaluated"] == 0
    assert series["points"][-8]["invited"] == 1
    assert sum(p["invited"] for p in series["points"]) == 3
    assert sum(p["completed"] for p in series["points"]) == 1
    assert [p["date"] for p in series["points"]] == sorted(p["date"] for p in series["points"])

    # Всё время: ряд начинается с первого события, а не с фиксированного окна.
    everything = (
        await client.get("/api/dashboard/timeseries?all_time=true", headers=bearer(token))
    ).json()
    assert len(everything["points"]) == 8
    assert everything["points"][0]["invited"] == 1

    # Короткий период отсекает старое приглашение.
    week = (
        await client.get(
            "/api/dashboard/timeseries",
            params={
                "from": (utcnow() - timedelta(days=3)).isoformat(),
                "vacancy_id": vacancy["id"],
            },
            headers=bearer(token),
        )
    ).json()
    assert week["vacancy_id"] == vacancy["id"]
    assert sum(p["invited"] for p in week["points"]) == 2


async def test_dashboard_requires_session(client: AsyncClient) -> None:
    assert (await client.get("/api/dashboard/overview")).status_code == 401
    assert (await client.get("/api/dashboard/timeseries")).status_code == 401
