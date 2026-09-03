"""Сид демо-данных: организация, роли, вакансии, воронка, заключения; идемпотентность."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from leonit.candidates.models import Interview, InterviewStatus
from leonit.core.db import get_session_maker
from leonit.demo.seed import DEMO_MODEL, PERSONAS, load_cases, seed
from leonit.evaluation.models import Evaluation, EvaluationStatus
from leonit.jobs.models import Job
from leonit.vacancies.models import Vacancy, VacancyStatus

PASSWORD = "demo-pass-2026"


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_seed_builds_demo_organization_and_is_idempotent(client: AsyncClient) -> None:
    email = f"demo-{uuid.uuid4().hex[:6]}@example.com"
    report = await seed(get_session_maker(), password=PASSWORD, email=email)
    assert report.created and len(report.vacancies) == 2
    assert report.interviews == len(PERSONAS) + 3 and report.evaluated == len(PERSONAS)

    again = await seed(get_session_maker(), password=PASSWORD, email=email)
    assert not again.created and again.interviews == 0 and again.evaluated == 0

    token = await _login(client, email)
    vacancies = await client.get("/api/vacancies", headers={"Authorization": f"Bearer {token}"})
    assert vacancies.status_code == 200
    titles = {item["title"] for item in vacancies.json()}
    assert titles == set(report.vacancies)
    async with get_session_maker()() as session:
        published = await session.scalar(
            select(func.count())
            .select_from(Vacancy)
            .where(Vacancy.title.in_(report.vacancies), Vacancy.status == VacancyStatus.published)
        )
        assert published == 2

    # Ранжирование по первой вакансии показывает баллы и рекомендации из заключений.
    first = next(item for item in vacancies.json() if item["title"] == report.vacancies[0])
    ranking = await client.get(
        f"/api/vacancies/{first['id']}/ranking", headers={"Authorization": f"Bearer {token}"}
    )
    assert ranking.status_code == 200, ranking.text
    scored = [item for item in ranking.json() if item["fit_score"] is not None]
    assert scored and {item["recommendation"] for item in scored} <= {
        "fit",
        "no_fit",
        "needs_check",
    }
    statuses = {item["status"] for item in ranking.json()}
    # Воронка: приглашённые, открывшие, в процессе и оценённые/решённые.
    assert {"invited", "opened", "in_progress"} <= statuses
    assert statuses & {"evaluated", "advanced", "rejected"}

    # Заключения помечены как демо и содержат проверенные цитаты.
    async with get_session_maker()() as session:
        rows = (
            await session.scalars(
                select(Evaluation)
                .join(Interview)
                .where(Interview.vacancy_id == uuid.UUID(first["id"]))
            )
        ).all()
        assert rows and all(row.model == DEMO_MODEL for row in rows)
        assert all(row.status == EvaluationStatus.done for row in rows)
        assert any((row.quotes_found or 0) > 0 for row in rows)
        decided = await session.scalar(
            select(func.count())
            .select_from(Interview)
            .where(Interview.status.in_([InterviewStatus.advanced, InterviewStatus.rejected]))
        )
        assert decided is not None and decided >= 2

    # Рекрутер и нанимающий менеджер входят тем же паролем; менеджер видит только свою вакансию.
    manager = await _login(client, report.manager_email)
    visible = await client.get("/api/vacancies", headers={"Authorization": f"Bearer {manager}"})
    assert visible.status_code == 200 and len(visible.json()) == 1
    await _login(client, report.recruiter_email)


async def test_seed_real_mode_enqueues_evaluation_jobs() -> None:
    email = f"demo-{uuid.uuid4().hex[:6]}@example.com"
    report = await seed(get_session_maker(), password=PASSWORD, email=email, evaluate="real")
    assert report.queued_for_evaluation == len(PERSONAS) and report.evaluated == 0
    async with get_session_maker()() as session:
        queued = await session.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.kind == "interview.process", Job.dedupe_key.like("interview:%"))
        )
        assert queued is not None and queued >= len(PERSONAS)


def test_dataset_cases_have_personas() -> None:
    _, cases = load_cases()
    assert {case["_code"] for case in cases} == set(PERSONAS)
