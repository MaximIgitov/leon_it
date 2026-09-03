"""Задача ``interview.process``: дождаться транскриптов и оценить интервью.

Транскрибация ответов идёт отдельными задачами (``answer.process``), поэтому
оценка не блокирует воркер ожиданием: если у зачётных ответов обработка ещё не
закончилась, задача завершается результатом ``{"waiting": n}`` и ставит себя
заново через паузу. Ограничение на число повторов защищает от вечного
ожидания при зависшем ответе — тогда оцениваем то, что есть, с пометкой
«транскрипт недоступен».

Гонки: по одному интервью в очереди может оказаться несколько задач (ожидание
транскриптов, «Переобработать»). Модель вызывает только одна — та, что
захватила интервью условным UPDATE ``completed → processing``, либо, если
интервью уже в ``processing``, самая ранняя из выполняющихся задач; остальные
завершаются результатом ``skipped``. «Переобработать» отвечает 409, пока по
интервью есть незавершённая задача.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
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
from leonit.jobs.models import Job, JobStatus
from leonit.jobs.registry import JobContext, job

log = get_logger(__name__)

WAIT_RETRY_S = 15
# 80 × 15 с = 20 минут: дольше транскрибация нескольких ответов не идёт.
WAIT_MAX_RETRIES = 80


async def pending_answers(session: AsyncSession, interview_id: UUID) -> int:
    finals = pick_final_answers(await final_answers(session, interview_id))
    return sum(1 for answer in finals.values() if answer.status in PENDING_ANSWER_STATUSES)


async def active_jobs(session: AsyncSession, interview_id: UUID) -> list[Job]:
    """Незавершённые задачи оценки по интервью (базовый ключ, ожидание, переобработка)."""
    rows = await session.scalars(
        select(Job)
        .where(
            Job.kind == INTERVIEW_PROCESS_JOB,
            Job.dedupe_key.like(f"interview:{interview_id}%"),
            Job.status.in_([JobStatus.queued, JobStatus.running]),
        )
        .order_by(Job.created_at, Job.id)
    )
    return list(rows)


async def _claim_interview(session: AsyncSession, interview_id: UUID) -> bool:
    """``completed → processing`` одним условным UPDATE: кто успел, тот и оценивает."""
    result = await session.execute(
        update(Interview)
        .where(Interview.id == interview_id, Interview.status == InterviewStatus.completed)
        .values(status=InterviewStatus.processing, processed_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return bool(result.rowcount)


async def _another_job_is_running(session: AsyncSession, interview_id: UUID, job_id: UUID) -> bool:
    """Есть ли по интервью более ранняя выполняющаяся задача оценки."""
    mine = await session.get(Job, job_id)
    for other in await active_jobs(session, interview_id):
        if other.id == job_id or other.status != JobStatus.running:
            continue
        if mine is None or (other.created_at, str(other.id)) < (mine.created_at, str(mine.id)):
            return True
    return False


@job(INTERVIEW_PROCESS_JOB, resource="llm")
async def process_interview(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any] | None:
    interview_id = UUID(str(payload["interview_id"]))
    waited = int(payload.get("waited", 0))
    async with ctx.session_maker() as session:
        interview = await session.get(Interview, interview_id)
        if interview is None:
            return {"skipped": "interview not found", "interview_id": str(interview_id)}
        if interview.status == InterviewStatus.completed:
            if not await _claim_interview(session, interview_id):
                return {"skipped": "interview claimed by another job"}
            await session.refresh(interview)
        elif interview.status != InterviewStatus.processing:
            # Отменено, уже оценено параллельной задачей и т. п. — не трогаем.
            return {"skipped": f"interview is {interview.status.value}"}
        elif await _another_job_is_running(session, interview_id, ctx.job_id):
            return {"skipped": "another job is evaluating this interview"}

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


def reset_evaluation(evaluation: Evaluation) -> None:
    """Обнулить результат перед переоценкой: пока идёт новая, старых баллов не видно."""
    evaluation.status = EvaluationStatus.pending
    evaluation.fit_score = None
    evaluation.recommendation = None
    evaluation.output = None
    evaluation.candidate_feedback = None
    evaluation.raw_response = None
    evaluation.usage = None
    evaluation.error = None
    evaluation.evaluated_at = None
    evaluation.quotes_found = None
    evaluation.quotes_total = None


async def reprocess(session: AsyncSession, actor: Actor, interview_id: UUID) -> Job:
    """Кнопка «Переобработать»: сбросить заключение и поставить оценку заново.

    Допускается для оценённого интервью, для завершённого, которое ещё не
    взяли в работу, и для зависшего в ``processing`` с заключением ``failed``.
    Пока по интервью есть незавершённая задача оценки — 409.
    """
    interview = await InterviewService(session).get(actor, interview_id)
    authorize(actor, "candidate.write", vacancy_id=interview.vacancy_id)
    active = await active_jobs(session, interview.id)
    if active:
        raise ConflictError(
            "Оценка этого интервью уже выполняется или стоит в очереди — дождитесь результата"
        )
    evaluation = await session.scalar(
        select(Evaluation).where(Evaluation.interview_id == interview.id)
    )
    if interview.status == InterviewStatus.evaluated:
        transition(interview, InterviewStatus.processing)
        interview.processed_at = utcnow()
        interview.evaluated_at = None
    elif interview.status == InterviewStatus.processing:
        if evaluation is None or evaluation.status != EvaluationStatus.failed:
            raise ConflictError(
                "Интервью уже обрабатывается; переобработка возможна после ошибки оценки"
            )
    elif interview.status != InterviewStatus.completed:
        raise ConflictError(
            "Переобработать можно только завершённое или оценённое интервью, "
            f"сейчас {interview.status.value}"
        )
    if evaluation is None:
        evaluation = Evaluation(interview_id=interview.id, prompt_version=PROMPT_VERSION)
        session.add(evaluation)
    reset_evaluation(evaluation)
    # Суффикс попытки: завершённые задачи с прежними ключами остаются в истории.
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
