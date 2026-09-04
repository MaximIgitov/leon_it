from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from leonit.accounts.deps import CurrentActor
from leonit.core.deps import DbSession
from leonit.integrity import service

router = APIRouter(prefix="/interviews", tags=["reports"])


class ObservationReview(BaseModel):
    verdict: Literal["confirmed", "false_positive"]
    comment: str | None
    reviewer: str
    reviewed_at: datetime


class ObservationOut(BaseModel):
    code: str
    level: Literal["info", "attention", "risk"]
    title: str
    detail: str
    question_index: int | None
    evidence: dict[str, Any]
    review: ObservationReview | None


class IntegrityOut(BaseModel):
    level: Literal["info", "attention", "risk"]
    level_label: str
    observations: list[ObservationOut]
    checked: bool
    flags: int


class ReviewIn(BaseModel):
    code: str = Field(max_length=64)
    question_index: int | None = Field(default=None, ge=0)
    verdict: Literal["confirmed", "false_positive"]
    comment: str = Field(default="", max_length=2000)


@router.get("/{interview_id}/integrity", response_model=IntegrityOut)
async def get_integrity(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> IntegrityOut:
    return IntegrityOut.model_validate(await service.get_report(session, actor, interview_id))


@router.post("/{interview_id}/integrity/review", response_model=IntegrityOut)
async def review_integrity(
    interview_id: UUID, payload: ReviewIn, actor: CurrentActor, session: DbSession
) -> IntegrityOut:
    report = await service.review_observation(
        session,
        actor,
        interview_id,
        code=payload.code,
        question_index=payload.question_index,
        verdict=payload.verdict,
        comment=payload.comment,
    )
    return IntegrityOut.model_validate(report)
