"""Письма по ходу найма: напоминание, «заключение готово», обратная связь, отписка."""

from __future__ import annotations

import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from leonit.candidates.models import Candidate, Interview, InterviewStatus
from leonit.core.db import get_session_maker
from leonit.core.time import utcnow
from leonit.evaluation.models import Evaluation, EvaluationStatus
from leonit.jobs.models import Job, JobStatus
from leonit.jobs.registry import get_handler, load_all_handlers, tick_hooks
from leonit.notifications import jobs as notification_jobs
from leonit.notifications.models import EmailMessage
from leonit.notifications.outreach import (
    EMAIL_KIND_CANDIDATE_FEEDBACK,
    EMAIL_KIND_EVALUATION_READY,
    EMAIL_KIND_REMINDER,
    FEEDBACK_JOB,
    REMINDER_JOB,
    schedule_reminders,
    send_candidate_feedback,
    send_reminder,
)
from leonit.notifications.unsubscribe import sign_unsubscribe_token, unsubscribe_link
from leonit.vacancies.models import CandidateFeedbackMode, Vacancy
from tests.helpers import bearer, create_invite, invite_token_from_url, register
from tests.test_candidates import _invite, _published_vacancy, _token

FEEDBACK_PAYLOAD = {
    "greeting": "Здравствуйте!",
    "strengths": ["Чётко объясняете решения", "Приводите примеры из практики"],
    "suggestions": ["Разберите планы запросов", "Добавляйте детали про компромиссы"],
    "closing": "Успехов на собеседованиях!",
}


async def _emails(kind: str | None = None, interview_id: str | None = None) -> list[EmailMessage]:
    """Письма из outbox. База в тестах общая, поэтому фильтр по интервью обязателен."""
    async with get_session_maker()() as session:
        stmt = select(EmailMessage).order_by(EmailMessage.created_at)
        if kind:
            stmt = stmt.where(EmailMessage.kind == kind)
        if interview_id:
            stmt = stmt.where(EmailMessage.interview_id == uuid.UUID(interview_id))
        return list(await session.scalars(stmt))


async def _set_interview(interview_id: str, **values: object) -> None:
    async with get_session_maker()() as session:
        await session.execute(
            update(Interview).where(Interview.id == uuid.UUID(interview_id)).values(**values)
        )
        await session.commit()


async def _set_vacancy(vacancy_id: str, **values: object) -> None:
    async with get_session_maker()() as session:
        await session.execute(
            update(Vacancy).where(Vacancy.id == uuid.UUID(vacancy_id)).values(**values)
        )
        await session.commit()


# ---------------------------------------------------------------- напоминание


async def test_reminder_is_sent_once_and_only_inside_window(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    soon = await _invite(client, token, vacancy["id"], "soon@example.com")
    later = await _invite(client, token, vacancy["id"], "later@example.com")
    done = await _invite(client, token, vacancy["id"], "done@example.com")

    now = utcnow()
    # Ссылка истекает через сутки — напоминаем; через неделю — рано.
    await _set_interview(soon["id"], expires_at=now + timedelta(hours=24))
    await _set_interview(later["id"], expires_at=now + timedelta(days=7))
    await _set_interview(
        done["id"], expires_at=now + timedelta(hours=24), status=InterviewStatus.completed
    )

    async with get_session_maker()() as session:
        assert await schedule_reminders(session) == 1
        queued = await session.scalar(select(Job).where(Job.dedupe_key == f"reminder:{soon['id']}"))
        assert queued is not None and queued.kind == REMINDER_JOB
        # Повторный проход дублей не ставит.
        assert await schedule_reminders(session) == 0

    async with get_session_maker()() as session:
        result = await send_reminder(session, uuid.UUID(soon["id"]))
    assert "email_id" in result
    (letter,) = await _emails(EMAIL_KIND_REMINDER, soon["id"])
    assert letter.to_email == "soon@example.com"
    assert "Напоминание" in letter.subject and "/i/" in letter.body_text
    # Баллов и оценок в письме кандидату нет.
    assert "балл" not in letter.body_text.lower()

    # Второй раз не шлём даже прямым вызовом.
    async with get_session_maker()() as session:
        again = await send_reminder(session, uuid.UUID(soon["id"]))
    assert again == {"skipped": "reminder already sent"}
    assert len(await _emails(EMAIL_KIND_REMINDER, soon["id"])) == 1

    # Напоминание повторяет ту же ссылку: и она, и первое письмо продолжают работать.
    link = next(line for line in letter.body_text.splitlines() if "/i/" in line)
    assert _token(link) == _token(soon["link"])
    page = await client.get(f"/api/public/invitations/{_token(link)}")
    assert page.status_code == 200, page.text


async def test_reminder_keeps_hh_link_when_token_is_not_stored(client: AsyncClient) -> None:
    """Старое интервью из hh без сохранённого токена: ссылку в чате не ломаем."""
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    invited = await _invite(client, token, vacancy["id"], "hh@example.com")
    now = utcnow()
    async with get_session_maker()() as session:
        interview = await session.get(Interview, uuid.UUID(invited["id"]))
        assert interview is not None
        interview.token_secret = None
        interview.external_ref = "hh:5556000000"
        interview.expires_at = now + timedelta(hours=12)
        before = interview.token_hash
        await session.commit()
        result = await send_reminder(session, uuid.UUID(invited["id"]))
    assert "email_id" in result
    (letter,) = await _emails(EMAIL_KIND_REMINDER, invited["id"])
    assert "/i/" not in letter.body_text and "hh.ru" in letter.body_text
    async with get_session_maker()() as session:
        interview = await session.get(Interview, uuid.UUID(invited["id"]))
        assert interview is not None and interview.token_hash == before
    page = await client.get(f"/api/public/invitations/{_token(invited['link'])}")
    assert page.status_code == 200, page.text


async def test_reminder_skips_finished_and_expired(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "expired@example.com")
    await _set_interview(interview["id"], expires_at=utcnow() - timedelta(hours=1))
    async with get_session_maker()() as session:
        assert await send_reminder(session, uuid.UUID(interview["id"])) == {
            "skipped": "link already expired"
        }
        assert await send_reminder(session, uuid.uuid4()) == {"skipped": "interview not found"}
    assert await _emails(EMAIL_KIND_REMINDER, interview["id"]) == []


async def test_reminder_tick_hook_is_registered() -> None:
    load_all_handlers()
    assert notification_jobs.schedule_reminders_tick in tick_hooks()
    assert get_handler(REMINDER_JOB) is not None
    assert get_handler(FEEDBACK_JOB) is not None


# ------------------------------------------------------- заключение готово


async def _evaluated_interview(client: AsyncClient) -> tuple[str, dict, dict]:
    """Интервью с готовым заключением: письма отправляются при его сохранении."""
    from leonit.evaluation.jobs import process_interview
    from tests.test_evaluation import _completed_interview, _ctx, _finish_answers

    token, interview, vacancy, _ = await _completed_interview(client)
    await _finish_answers(interview["id"])
    await process_interview({"interview_id": interview["id"]}, _ctx())
    return token, interview, vacancy


async def test_evaluation_ready_reaches_recruiter_and_scoped_manager(
    client: AsyncClient,
) -> None:
    token, interview, vacancy = await _evaluated_interview(client)
    # Менеджер с этой вакансией в периметре и менеджер с чужой.
    allowed = await create_invite(
        client, token, role="hiring_manager", vacancy_scope=[vacancy["id"]]
    )
    await register(client, invite_token=invite_token_from_url(allowed["url"]))
    other_vacancy = await _published_vacancy(client, token, "Другая вакансия")
    denied = await create_invite(
        client, token, role="hiring_manager", vacancy_scope=[other_vacancy["id"]]
    )
    await register(client, invite_token=invite_token_from_url(denied["url"]))

    # Письма о первом заключении ушли до появления менеджеров — переоцениваем.
    async with get_session_maker()() as session:
        await session.execute(
            update(Job)
            .where(Job.dedupe_key.like(f"interview:{interview['id']}%"))
            .values(status=JobStatus.succeeded)
        )
        await session.commit()
    accepted = await client.post(
        f"/api/interviews/{interview['id']}/reprocess", headers=bearer(token)
    )
    assert accepted.status_code == 202, accepted.text
    from leonit.evaluation.jobs import process_interview
    from tests.test_evaluation import _ctx

    async with get_session_maker()() as session:
        job = await session.scalar(
            select(Job).where(Job.dedupe_key == f"interview:{interview['id']}:reprocess:1")
        )
        assert job is not None
    await process_interview(job.payload, _ctx())

    letters = await _emails(EMAIL_KIND_EVALUATION_READY, interview["id"])
    recipients = {letter.to_email for letter in letters}
    manager_email = next(
        row["email"]
        for row in (await client.get("/api/organization/members", headers=bearer(token))).json()
        if row["role"] == "hiring_manager" and row["vacancy_scope"] == [vacancy["id"]]
    )
    assert manager_email in recipients
    other_email = next(
        row["email"]
        for row in (await client.get("/api/organization/members", headers=bearer(token))).json()
        if row["role"] == "hiring_manager" and row["vacancy_scope"] == [other_vacancy["id"]]
    )
    assert other_email not in recipients
    updated = [letter for letter in letters if "обновлено" in letter.subject]
    assert updated and "/interviews/" in updated[0].body_text


# ------------------------------------------------------ обратная связь


async def _set_feedback(interview_id: str, payload: dict | None = FEEDBACK_PAYLOAD) -> None:
    async with get_session_maker()() as session:
        await session.execute(
            update(Evaluation)
            .where(Evaluation.interview_id == uuid.UUID(interview_id))
            .values(candidate_feedback=payload, status=EvaluationStatus.done)
        )
        await session.commit()


async def test_feedback_is_scheduled_after_evaluation_and_sent_with_unsubscribe(
    client: AsyncClient,
) -> None:
    _, interview, vacancy = await _evaluated_interview(client)
    await _set_vacancy(
        vacancy["id"],
        candidate_feedback_mode=CandidateFeedbackMode.auto_after_days,
        candidate_feedback_after_days=2,
    )
    await _set_feedback(interview["id"])
    async with get_session_maker()() as session:
        interview_row = await session.get(Interview, uuid.UUID(interview["id"]))
        assert interview_row is not None
        from leonit.notifications.outreach import schedule_candidate_feedback

        job = await schedule_candidate_feedback(session, interview_row, decided=False)
        await session.commit()
    assert job is not None and job.dedupe_key == f"feedback:{interview['id']}"
    # Письмо не «сейчас», а через настроенные дни.
    assert job.run_after > utcnow() + timedelta(days=1)

    async with get_session_maker()() as session:
        result = await send_candidate_feedback(session, uuid.UUID(interview["id"]))
    assert "email_id" in result
    (letter,) = await _emails(EMAIL_KIND_CANDIDATE_FEEDBACK, interview["id"])
    assert "Обратная связь" in letter.subject
    assert "Чётко объясняете решения" in letter.body_text
    assert "/unsubscribe/" in letter.body_text
    # В письме кандидату нет баллов, рекомендации и решения.
    lowered = letter.body_text.lower()
    assert "балл" not in lowered and "подходит" not in lowered and "fit" not in lowered


async def test_feedback_respects_mode_decision_and_unsubscribe(client: AsyncClient) -> None:
    token, interview, vacancy = await _evaluated_interview(client)
    await _set_feedback(interview["id"])

    # off — не шлём даже прямым вызовом.
    await _set_vacancy(vacancy["id"], candidate_feedback_mode=CandidateFeedbackMode.off)
    async with get_session_maker()() as session:
        assert await send_candidate_feedback(session, uuid.UUID(interview["id"])) == {
            "skipped": "feedback disabled for vacancy"
        }

    # after_decision — только после решения ревьюера.
    await _set_vacancy(
        vacancy["id"],
        candidate_feedback_mode=CandidateFeedbackMode.after_decision,
        candidate_feedback_after_days=1,
    )
    async with get_session_maker()() as session:
        assert await send_candidate_feedback(session, uuid.UUID(interview["id"])) == {
            "skipped": "decision is not made yet"
        }
    decided = await client.post(
        f"/api/interviews/{interview['id']}/decision",
        json={"decision": "reject", "note": "не хватило глубины"},
        headers=bearer(token),
    )
    assert decided.status_code == 200, decided.text
    async with get_session_maker()() as session:
        scheduled = await session.scalar(
            select(Job).where(Job.dedupe_key == f"feedback:{interview['id']}")
        )
        assert scheduled is not None and scheduled.kind == FEEDBACK_JOB

    # Кандидат отписался — письмо не уходит.
    async with get_session_maker()() as session:
        candidate_id = await session.scalar(
            select(Interview.candidate_id).where(Interview.id == uuid.UUID(interview["id"]))
        )
        await session.execute(
            update(Candidate).where(Candidate.id == candidate_id).values(unsubscribed_at=utcnow())
        )
        await session.commit()
    async with get_session_maker()() as session:
        assert await send_candidate_feedback(session, uuid.UUID(interview["id"])) == {
            "skipped": "candidate unsubscribed"
        }
    assert await _emails(EMAIL_KIND_CANDIDATE_FEEDBACK, interview["id"]) == []


async def test_feedback_without_text_is_skipped(client: AsyncClient) -> None:
    _, interview, vacancy = await _evaluated_interview(client)
    await _set_vacancy(vacancy["id"], candidate_feedback_mode=CandidateFeedbackMode.auto_after_days)
    await _set_feedback(interview["id"], payload=None)
    async with get_session_maker()() as session:
        assert await send_candidate_feedback(session, uuid.UUID(interview["id"])) == {
            "skipped": "no feedback text"
        }


# ---------------------------------------------------------------- отписка


async def test_unsubscribe_link_is_signed_and_idempotent(client: AsyncClient) -> None:
    _, token = await register(client)
    vacancy = await _published_vacancy(client, token)
    interview = await _invite(client, token, vacancy["id"], "reader@example.com")
    async with get_session_maker()() as session:
        candidate_id = await session.scalar(
            select(Interview.candidate_id).where(Interview.id == uuid.UUID(interview["id"]))
        )
        await session.execute(
            update(Candidate).where(Candidate.id == candidate_id).values(newsletter_opt_in=True)
        )
        await session.commit()

    link = unsubscribe_link(candidate_id)

    token_value = link.rsplit("/", 1)[-1]
    first = await client.post(f"/api/public/unsubscribe/{token_value}")
    assert first.status_code == 200 and first.json() == {"already": False}
    second = await client.post(f"/api/public/unsubscribe/{token_value}")
    assert second.status_code == 200 and second.json() == {"already": True}

    async with get_session_maker()() as session:
        candidate = await session.get(Candidate, candidate_id)
        assert candidate is not None
        assert candidate.unsubscribed_at is not None and candidate.newsletter_opt_in is False
        from leonit.candidates.models import ConsentRecord

        records = list(
            await session.scalars(
                select(ConsentRecord).where(
                    ConsentRecord.candidate_id == candidate_id,
                    ConsentRecord.slug == "newsletter-consent",
                )
            )
        )
        assert any(record.accepted is False for record in records)

    # Подделка, чужая подпись и неизвестный кандидат — 404.
    assert (await client.post("/api/public/unsubscribe/garbage")).status_code == 404
    stranger = sign_unsubscribe_token(uuid.uuid4())
    assert (await client.post(f"/api/public/unsubscribe/{stranger}")).status_code == 404
