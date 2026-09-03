"""Письма по ходу найма: напоминание, «заключение готово», обратная связь кандидату.

Три сценария, у каждого свой триггер:

* **Напоминание** — тик воркера раз в час смотрит интервью, которые кандидат не
  довёл до конца, а ссылка истекает в ближайшие ``REMINDER_BEFORE_HOURS``.
  Отправляется один раз на интервью (``reminder_sent_at``). Ссылка не хранится в
  открытом виде, поэтому напоминание выпускает новый токен и продлевает
  приглашение — тот же механизм, что у кнопки «Отправить ссылку заново».
* **Заключение готово** — вызывается после сохранения оценки: письмо рекрутеру,
  который пригласил кандидата, и активным нанимающим менеджерам, у которых эта
  вакансия в периметре. Повторная оценка шлёт письмо «обновлено».
* **Обратная связь кандидату** — задача с задержкой по настройке вакансии:
  ``auto_after_days`` — через N дней после заключения, ``after_decision`` — через
  N дней после решения ревьюера, ``off`` — не шлём. Перед отправкой настройка и
  наличие текста проверяются заново, отписавшимся кандидатам письма не уходят.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.accounts.models import Membership, MembershipRole, Organization, User
from leonit.candidates.models import Candidate, Interview, InterviewStatus
from leonit.core.config import get_settings
from leonit.core.logging import get_logger
from leonit.core.time import aware, utcnow
from leonit.jobs import service as jobs
from leonit.jobs.models import Job
from leonit.notifications.service import queue_email
from leonit.notifications.templates import (
    candidate_feedback_email,
    evaluation_ready_email,
    reminder_email,
)
from leonit.notifications.unsubscribe import unsubscribe_link
from leonit.vacancies.models import CandidateFeedbackMode, Vacancy

log = get_logger(__name__)

REMINDER_JOB = "interview.reminder"
FEEDBACK_JOB = "interview.feedback"
# За сколько до истечения ссылки напоминаем и сколько времени на прохождение
# должно остаться, чтобы напоминание имело смысл.
REMINDER_BEFORE_HOURS = 48
REMINDER_MIN_HOURS = 1
# Статусы, в которых кандидат ещё может пройти интервью.
UNFINISHED_STATUSES: tuple[InterviewStatus, ...] = (
    InterviewStatus.invited,
    InterviewStatus.opened,
    InterviewStatus.consented,
    InterviewStatus.in_progress,
)
EMAIL_KIND_REMINDER = "interview.reminder"
EMAIL_KIND_EVALUATION_READY = "interview.evaluation_ready"
EMAIL_KIND_CANDIDATE_FEEDBACK = "interview.candidate_feedback"


# ------------------------------------------------------------- напоминание


async def due_reminders(session: AsyncSession, *, now: datetime | None = None) -> list[Interview]:
    """Интервью, которым пора напомнить: ссылка истекает, а кандидат не закончил."""
    now = now or utcnow()
    rows = await session.scalars(
        select(Interview)
        .where(
            Interview.status.in_(UNFINISHED_STATUSES),
            Interview.reminder_sent_at.is_(None),
            Interview.expires_at > now + timedelta(hours=REMINDER_MIN_HOURS),
            Interview.expires_at <= now + timedelta(hours=REMINDER_BEFORE_HOURS),
        )
        .options(selectinload(Interview.candidate))
    )
    return list(rows)


async def schedule_reminders(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Поставить задачи напоминаний; вызывается тиком воркера."""
    queued = 0
    for interview in await due_reminders(session, now=now):
        dedupe_key = f"reminder:{interview.id}"
        # Задача по этому интервью уже в очереди или выполняется: тик раз в час
        # не должен ставить её заново, пока письмо не ушло.
        existing = await session.scalar(select(Job).where(Job.dedupe_key == dedupe_key))
        if existing is not None and not existing.is_terminal:
            continue
        await jobs.enqueue(
            session,
            REMINDER_JOB,
            {"interview_id": str(interview.id)},
            dedupe_key=dedupe_key,
            max_attempts=3,
        )
        queued += 1
    if queued:
        await session.commit()
    return queued


async def send_reminder(session: AsyncSession, interview_id: UUID) -> dict[str, Any]:
    """Отправить одно напоминание. Идемпотентно по ``reminder_sent_at``."""
    from leonit.accounts.security import generate_link_token, hash_link_token
    from leonit.candidates.service import estimated_minutes, interview_link

    interview = await session.scalar(
        select(Interview)
        .where(Interview.id == interview_id)
        .options(selectinload(Interview.candidate))
    )
    if interview is None:
        return {"skipped": "interview not found"}
    if interview.reminder_sent_at is not None:
        return {"skipped": "reminder already sent"}
    if interview.status not in UNFINISHED_STATUSES:
        return {"skipped": f"interview is {interview.status.value}"}
    now = utcnow()
    expires_at = aware(interview.expires_at)
    assert expires_at is not None
    if expires_at <= now:
        return {"skipped": "link already expired"}

    vacancy = await session.scalar(
        select(Vacancy)
        .where(Vacancy.id == interview.vacancy_id)
        .options(selectinload(Vacancy.questions))
    )
    organization = await session.get(Organization, interview.organization_id)
    if vacancy is None or organization is None:
        return {"skipped": "vacancy or organization is gone"}

    # Токен интервью хранится хешем, поэтому ссылку в письме выпускаем заново —
    # старая перестаёт работать, как и при «Отправить ссылку заново».
    token = generate_link_token()
    interview.token_hash = hash_link_token(token)
    interview.reminder_sent_at = now
    subject, body = reminder_email(
        candidate_name=interview.consent_full_name or interview.candidate.full_name,
        organization_name=organization.name,
        vacancy_title=vacancy.title,
        link=interview_link(token),
        expires_at=expires_at,
        estimated_minutes=estimated_minutes(vacancy),
    )
    message = await queue_email(
        session,
        organization_id=organization.id,
        to_email=interview.consent_email or interview.candidate.email,
        subject=subject,
        body_text=body,
        kind=EMAIL_KIND_REMINDER,
        interview_id=interview.id,
    )
    await session.commit()
    log.info("reminder.sent interview=%s email=%s", interview.id, message.id)
    return {"interview_id": str(interview.id), "email_id": str(message.id)}


# --------------------------------------------------------- заключение готово


async def evaluation_recipients(
    session: AsyncSession, interview: Interview
) -> list[tuple[str, str | None]]:
    """Кому сообщить о заключении: пригласивший рекрутер и менеджеры с этой вакансией."""
    recipients: dict[str, str | None] = {}
    if interview.invited_by_user_id:
        recruiter = await session.get(User, interview.invited_by_user_id)
        if recruiter is not None and recruiter.is_active:
            recipients[recruiter.email] = recruiter.full_name
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == interview.organization_id,
            Membership.role == MembershipRole.hiring_manager,
            Membership.is_active.is_(True),
        )
    )
    for membership, user in rows.all():
        if not user.is_active:
            continue
        scope = membership.vacancy_scope
        if scope is not None and str(interview.vacancy_id) not in scope:
            continue
        recipients.setdefault(user.email, user.full_name)
    return [(email, name) for email, name in recipients.items()]


async def notify_evaluation_ready(
    session: AsyncSession,
    interview: Interview,
    *,
    fit_score: float | None,
    recommendation: str | None,
) -> int:
    """Письма о готовом заключении. Ошибка письма не должна ронять оценку.

    «Обновлено» вместо «готово» — если по этому интервью письмо уже уходило:
    после переобработки получатели должны понимать, что заключение изменилось,
    а не думать, что пришёл дубль.
    """
    from leonit.notifications.models import EmailMessage

    already = await session.scalar(
        select(EmailMessage.id)
        .where(
            EmailMessage.interview_id == interview.id,
            EmailMessage.kind == EMAIL_KIND_EVALUATION_READY,
        )
        .limit(1)
    )
    updated = already is not None
    vacancy = await session.get(Vacancy, interview.vacancy_id)
    candidate = interview.candidate or await session.get(Candidate, interview.candidate_id)
    if vacancy is None or candidate is None:
        return 0
    link = f"{get_settings().PUBLIC_URL}/vacancies/{interview.vacancy_id}/interviews/{interview.id}"
    sent = 0
    for email, name in await evaluation_recipients(session, interview):
        subject, body = evaluation_ready_email(
            recipient_name=name,
            candidate_name=candidate.full_name,
            vacancy_title=vacancy.title,
            link=link,
            recommendation=recommendation,
            fit_score=fit_score,
            updated=updated,
        )
        await queue_email(
            session,
            organization_id=interview.organization_id,
            to_email=email,
            subject=subject,
            body_text=body,
            kind=EMAIL_KIND_EVALUATION_READY,
            interview_id=interview.id,
        )
        sent += 1
    log.info("evaluation.ready interview=%s recipients=%s", interview.id, sent)
    return sent


# ------------------------------------------------------ обратная связь


def feedback_delay(vacancy: Vacancy, *, decided: bool) -> timedelta | None:
    """Через сколько слать обратную связь; None — не слать по этой настройке."""
    mode = vacancy.candidate_feedback_mode
    if mode == CandidateFeedbackMode.off:
        return None
    if mode == CandidateFeedbackMode.after_decision and not decided:
        return None
    return timedelta(days=max(int(vacancy.candidate_feedback_after_days), 0))


async def schedule_candidate_feedback(
    session: AsyncSession, interview: Interview, *, decided: bool, now: datetime | None = None
) -> Job | None:
    """Поставить отложенную задачу на обратную связь кандидату."""
    vacancy = await session.get(Vacancy, interview.vacancy_id)
    if vacancy is None:
        return None
    delay = feedback_delay(vacancy, decided=decided)
    if delay is None:
        return None
    now = now or utcnow()
    return await jobs.enqueue(
        session,
        FEEDBACK_JOB,
        {"interview_id": str(interview.id)},
        run_after=now + delay,
        dedupe_key=f"feedback:{interview.id}",
        max_attempts=3,
    )


async def send_candidate_feedback(session: AsyncSession, interview_id: UUID) -> dict[str, Any]:
    """Отправить обратную связь кандидату, если настройка и согласие ещё в силе."""
    from leonit.evaluation.models import Evaluation, EvaluationStatus

    interview = await session.scalar(
        select(Interview)
        .where(Interview.id == interview_id)
        .options(selectinload(Interview.candidate))
    )
    if interview is None:
        return {"skipped": "interview not found"}
    vacancy = await session.get(Vacancy, interview.vacancy_id)
    organization = await session.get(Organization, interview.organization_id)
    if vacancy is None or organization is None:
        return {"skipped": "vacancy or organization is gone"}
    if vacancy.candidate_feedback_mode == CandidateFeedbackMode.off:
        return {"skipped": "feedback disabled for vacancy"}
    if vacancy.candidate_feedback_mode == CandidateFeedbackMode.after_decision and not (
        interview.decision
    ):
        return {"skipped": "decision is not made yet"}
    candidate = interview.candidate
    if candidate.unsubscribed_at is not None:
        # Обратную связь по своему интервью кандидат получает без отдельной
        # галочки, но отписка от писем LeonIT её тоже отключает.
        return {"skipped": "candidate unsubscribed"}

    evaluation = await session.scalar(
        select(Evaluation).where(Evaluation.interview_id == interview.id)
    )
    if evaluation is None or evaluation.status != EvaluationStatus.done:
        return {"skipped": "evaluation is not ready"}
    payload = evaluation.candidate_feedback
    if not payload:
        return {"skipped": "no feedback text"}

    subject, body = candidate_feedback_email(
        organization_name=organization.name,
        vacancy_title=vacancy.title,
        greeting=str(payload.get("greeting") or "Здравствуйте!"),
        strengths=[str(item) for item in payload.get("strengths") or []],
        suggestions=[str(item) for item in payload.get("suggestions") or []],
        closing=str(payload.get("closing") or "Успехов!"),
        unsubscribe_link=unsubscribe_link(candidate.id),
    )
    message = await queue_email(
        session,
        organization_id=interview.organization_id,
        to_email=interview.consent_email or candidate.email,
        subject=subject,
        body_text=body,
        kind=EMAIL_KIND_CANDIDATE_FEEDBACK,
        interview_id=interview.id,
    )
    await session.commit()
    log.info("feedback.sent interview=%s email=%s", interview.id, message.id)
    return {"interview_id": str(interview.id), "email_id": str(message.id)}
