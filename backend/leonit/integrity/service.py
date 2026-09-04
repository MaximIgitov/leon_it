"""Сборка наблюдений по интервью и вердикты ревьюера."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.candidates.models import Interview
from leonit.candidates.service import InterviewService
from leonit.core.authz import Actor, authorize
from leonit.core.errors import NotFoundError, ValidationFailedError
from leonit.core.time import aware, utcnow
from leonit.integrity.models import IntegrityReview, IntegrityVerdict
from leonit.integrity.rules import (
    LEVEL_LABELS,
    LEVEL_ORDER,
    AnswerRow,
    EventRow,
    Observation,
    analyze,
    summary_level,
)
from leonit.interviews.models import Answer, AnswerStatus, InterviewEvent

# Наблюдение по интервью целиком хранится с этим индексом вопроса.
WHOLE_INTERVIEW = -1


async def _events(session: AsyncSession, interview_id: UUID) -> list[EventRow]:
    rows = await session.scalars(
        select(InterviewEvent)
        .where(InterviewEvent.interview_id == interview_id)
        .order_by(InterviewEvent.at_server, InterviewEvent.id)
    )
    return [
        EventRow(
            kind=row.kind,
            at_server=aware(row.at_server),  # type: ignore[arg-type]
            at_client_ms=row.at_client_ms,
            question_index=row.question_index,
            payload=row.payload or {},
        )
        for row in rows
    ]


async def _answers(session: AsyncSession, interview_id: UUID) -> list[AnswerRow]:
    rows = await session.scalars(
        select(Answer)
        .where(
            Answer.interview_id == interview_id,
            Answer.is_final.is_(True),
            Answer.status.notin_([AnswerStatus.recording, AnswerStatus.abandoned]),
        )
        .order_by(Answer.question_index, Answer.attempt)
    )
    return [
        AnswerRow(
            question_index=row.question_index,
            attempt=row.attempt,
            duration_ms=row.duration_ms,
            client_duration_ms=row.client_duration_ms,
            chunk_count=row.chunk_count,
            media_meta=row.media_meta or {},
            media_content_type=row.media_content_type,
            started_at=aware(row.recording_started_at),
            ended_at=aware(row.recording_ended_at),
        )
        for row in rows
    ]


async def _reviews(session: AsyncSession, interview_id: UUID) -> dict[tuple[str, int], Any]:
    rows = await session.scalars(
        select(IntegrityReview).where(IntegrityReview.interview_id == interview_id)
    )
    return {(row.code, row.question_index): row for row in rows}


def _observation_dict(observation: Observation, review: Any | None) -> dict[str, Any]:
    data = observation.as_dict()
    data["review"] = (
        None
        if review is None
        else {
            "verdict": review.verdict.value,
            "comment": review.comment,
            "reviewer": review.reviewer_label,
            "reviewed_at": aware(review.reviewed_at),
        }
    )
    return data


async def integrity_report(session: AsyncSession, interview_id: UUID) -> dict[str, Any]:
    """Наблюдения по интервью с вердиктами ревьюера и итоговым уровнем.

    Наблюдения, помеченные как ложное срабатывание, не влияют на итоговый
    уровень: ревьюер уже посмотрел и объяснил, почему это не проблема.
    """
    events = await _events(session, interview_id)
    answers = await _answers(session, interview_id)
    reviews = await _reviews(session, interview_id)
    observations = analyze(events, answers)
    items = [
        _observation_dict(
            observation,
            reviews.get(
                (
                    observation.code,
                    observation.question_index
                    if observation.question_index is not None
                    else WHOLE_INTERVIEW,
                )
            ),
        )
        for observation in observations
    ]
    counted = [
        observation
        for observation, item in zip(observations, items, strict=True)
        if (item["review"] or {}).get("verdict") != IntegrityVerdict.false_positive.value
    ]
    level = summary_level(counted)
    return {
        "level": level,
        "level_label": LEVEL_LABELS[level],
        "observations": items,
        "checked": bool(events or answers),
        "flags": sum(1 for observation in counted if LEVEL_ORDER[observation.level] > 0),
    }


async def get_report(session: AsyncSession, actor: Actor, interview_id: UUID) -> dict[str, Any]:
    interview = await InterviewService(session).get(actor, interview_id)
    authorize(actor, "report.read", vacancy_id=interview.vacancy_id)
    return await integrity_report(session, interview.id)


async def review_observation(
    session: AsyncSession,
    actor: Actor,
    interview_id: UUID,
    *,
    code: str,
    question_index: int | None,
    verdict: str,
    comment: str | None,
) -> dict[str, Any]:
    """Отметить наблюдение подтверждённым или ложным срабатыванием."""
    interview = await InterviewService(session).get(actor, interview_id)
    authorize(actor, "report.decide", vacancy_id=interview.vacancy_id)
    report = await integrity_report(session, interview.id)
    key = question_index if question_index is not None else WHOLE_INTERVIEW
    known = {
        (
            item["code"],
            item["question_index"] if item["question_index"] is not None else WHOLE_INTERVIEW,
        )
        for item in report["observations"]
    }
    if (code, key) not in known:
        raise NotFoundError("Такого наблюдения по интервью нет")
    try:
        value = IntegrityVerdict(verdict)
    except ValueError as error:
        raise ValidationFailedError("Неизвестное решение по наблюдению") from error

    existing = await session.scalar(
        select(IntegrityReview).where(
            IntegrityReview.interview_id == interview.id,
            IntegrityReview.code == code,
            IntegrityReview.question_index == key,
        )
    )
    if existing is None:
        existing = IntegrityReview(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            code=code,
            question_index=key,
        )
        session.add(existing)
    existing.verdict = value
    existing.comment = (comment or "").strip() or None
    existing.reviewed_by_user_id = actor.user.id
    existing.reviewer_label = actor.user.full_name or actor.user.email
    existing.reviewed_at = utcnow()
    await session.commit()
    return await integrity_report(session, interview.id)


async def flags_rate(session: AsyncSession, interview_ids: list[UUID]) -> float | None:
    """Доля интервью с непогашенными наблюдениями — для дашборда."""
    if not interview_ids:
        return None
    flagged = 0
    for interview_id in interview_ids:
        report = await integrity_report(session, interview_id)
        if report["flags"]:
            flagged += 1
    return round(flagged / len(interview_ids), 4)


async def interviews_with_flags(session: AsyncSession, interview_ids: list[UUID]) -> set[UUID]:
    result: set[UUID] = set()
    for interview_id in interview_ids:
        report = await integrity_report(session, interview_id)
        if report["flags"]:
            result.add(interview_id)
    return result


async def load_interview(session: AsyncSession, interview_id: UUID) -> Interview | None:
    return await session.get(Interview, interview_id)
