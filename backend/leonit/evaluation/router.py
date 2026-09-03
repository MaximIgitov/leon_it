from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from leonit.accounts.deps import CurrentActor
from leonit.candidates.models import Interview
from leonit.core.deps import DbSession
from leonit.core.errors import NotFoundError
from leonit.core.time import aware
from leonit.evaluation import service
from leonit.evaluation.jobs import reprocess
from leonit.evaluation.models import Evaluation
from leonit.evaluation.schemas import (
    CandidateFeedback,
    EvaluationOut,
    EvaluationOutput,
    RankingItem,
    ReprocessAccepted,
)

router = APIRouter(tags=["evaluation"])


def evaluation_out(interview: Interview, evaluation: Evaluation) -> EvaluationOut:
    return EvaluationOut(
        interview_id=str(interview.id),
        status=evaluation.status.value,  # type: ignore[arg-type]
        fit_score=evaluation.fit_score,
        recommendation=evaluation.recommendation,  # type: ignore[arg-type]
        output=EvaluationOutput.model_validate(evaluation.output) if evaluation.output else None,
        candidate_feedback=(
            CandidateFeedback.model_validate(evaluation.candidate_feedback)
            if evaluation.candidate_feedback
            else None
        ),
        model=evaluation.model,
        prompt_version=evaluation.prompt_version,
        evaluated_at=aware(evaluation.evaluated_at),
        error=evaluation.error,
        quotes_found=evaluation.quotes_found,
        quotes_total=evaluation.quotes_total,
    )


@router.get("/interviews/{interview_id}/evaluation", response_model=EvaluationOut)
async def get_evaluation(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> EvaluationOut:
    interview, evaluation = await service.get_evaluation(session, actor, interview_id)
    if evaluation is None:
        raise NotFoundError("Заключение по интервью ещё не готово")
    return evaluation_out(interview, evaluation)


@router.post(
    "/interviews/{interview_id}/reprocess",
    response_model=ReprocessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess_interview(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> ReprocessAccepted:
    job = await reprocess(session, actor, interview_id)
    return ReprocessAccepted(
        interview_id=str(interview_id), job_id=str(job.id), status=job.status.value
    )


@router.get("/vacancies/{vacancy_id}/ranking", response_model=list[RankingItem])
async def vacancy_ranking(
    vacancy_id: UUID, actor: CurrentActor, session: DbSession
) -> list[RankingItem]:
    return await service.ranking(session, actor, vacancy_id)
