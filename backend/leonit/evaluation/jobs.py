"""Задача ``interview.process``: дождаться транскриптов и оценить интервью.

Транскрибация ответов идёт отдельными задачами (``answer.process``), поэтому
оценка не блокирует воркер ожиданием: если у зачётных ответов обработка ещё не
закончилась, задача завершается результатом ``{"waiting": n}`` и ставит себя
заново через паузу. Ограничение на число повторов защищает от вечного
ожидания при зависшем ответе — тогда оцениваем то, что есть, с пометкой
«транскрипт недоступен».
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.candidates.models import Interview, InterviewStatus
from leonit.candidates.service import InterviewService, transition
from leonit.core.authz import Actor, authorize
from leonit.core.errors import ConflictError
from leonit.core.logging import get_logger
from leonit.core.time import utcnow
from leonit.evaluation.models import Evaluation, EvaluationStatus
from leonit.evaluation.prompts import PROMPT_VERSION
from leonit.evaluation.service import (
    PENDING_ANSWER_STATUSES,
    evaluate_interview,
    final_answers,
    pick_final_answers,
)
from leonit.interviews.service import INTERVIEW_PROCESS_JOB
from leonit.jobs import service as jobs
from leonit.jobs.models import Job
from leonit.jobs.registry import JobContext, job

log = get_logger(__name__)

WAIT_RETRY_S = 15
# 80 × 15 с = 20 минут: дольше транскрибация нескольких ответов не идёт.
WAIT_MAX_RETRIES = 80


async def pending_answers(session: AsyncSession, interview_id: UUID) -> int:
    finals = pick_final_answers(await final_answers(session, interview_id))
    return sum(1 for answer in finals.values() if answer.status in PENDING_ANSWER_STATUSES)


@job(INTERVIEW_PROCESS_JOB, resource="llm")
async def process_interview(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any] | None:
    interview_id = UUID(str(payload["interview_id"]))
    waited = int(payload.get("waited", 0))
    async with ctx.session_maker() as session:
        interview = await session.get(Interview, interview_id)
        if interview is None:
            return {"skipped": "interview not found", "interview_id": str(interview_id)}
        if interview.status == InterviewStatus.completed:
            transition(interview, InterviewStatus.processing)
            await session.commit()
        elif interview.status != InterviewStatus.processing:
            # Отменено, уже оценено параллельной задачей и т. п. — не трогаем.
            return {"skipped": f"interview is {interview.status.value}"}

        waiting = await pending_answers(session, interview_id)
        if waiting and waited < WAIT_MAX_RETRIES:
            attempt = waited + 1
            requeued = await jobs.enqueue(
                session,
                INTERVIEW_PROCESS_JOB,
                {**payload, "interview_id": str(interview_id), "waited": attempt},
                run_after=utcnow() + timedelta(seconds=WAIT_RETRY_S),
                dedupe_key=f"interview:{interview_id}:wait:{attempt}",
            )
            await session.commit()
            return {"waiting": waiting, "attempt": attempt, "next_job_id": str(requeued.id)}
        if waiting:
            log.warning("evaluation.wait_exhausted interview=%s pending=%s", interview_id, waiting)

        evaluation = await evaluate_interview(session, interview_id)
        return {
            "evaluation_id": str(evaluation.id),
            "status": evaluation.status.value,
            "fit_score": evaluation.fit_score,
            "recommendation": evaluation.recommendation,
            "waited": waited,
        }


async def reprocess(session: AsyncSession, actor: Actor, interview_id: UUID) -> Job:
    """Кнопка «Переобработать»: сбросить заключение и поставить оценку заново."""
    interview = await InterviewService(session).get(actor, interview_id)
    authorize(actor, "candidate.write", vacancy_id=interview.vacancy_id)
    if interview.status == InterviewStatus.evaluated:
        transition(interview, InterviewStatus.processing)
    elif interview.status not in (InterviewStatus.completed, InterviewStatus.processing):
        raise ConflictError(
            "Переобработать можно только завершённое или оценённое интервью, "
            f"сейчас {interview.status.value}"
        )
    evaluation = await session.scalar(
        select(Evaluation).where(Evaluation.interview_id == interview.id)
    )
    if evaluation is None:
        evaluation = Evaluation(interview_id=interview.id, prompt_version=PROMPT_VERSION)
        session.add(evaluation)
    evaluation.status = EvaluationStatus.pending
    evaluation.error = None
    # Суффикс попытки: активная задача с базовым ключом могла ещё висеть в очереди.
    previous = await session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.dedupe_key.like(f"interview:{interview.id}:reprocess:%"))
    )
    attempt = int(previous or 0) + 1
    requeued = await jobs.enqueue(
        session,
        INTERVIEW_PROCESS_JOB,
        {"interview_id": str(interview.id), "reprocess": attempt},
        dedupe_key=f"interview:{interview.id}:reprocess:{attempt}",
    )
    await session.commit()
    return requeued
