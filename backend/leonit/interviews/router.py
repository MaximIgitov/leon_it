from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from leonit.accounts.deps import CurrentActor
from leonit.candidates.models import Interview
from leonit.candidates.router import _client_ip, public_rate_limiter
from leonit.core.deps import DbSession
from leonit.core.errors import ValidationFailedError
from leonit.core.storage import StorageOffsetConflict
from leonit.core.time import aware
from leonit.interviews.code import code_submission_out, report_transcript
from leonit.interviews.models import Answer, InterviewEvent
from leonit.interviews.schemas import (
    AnswerComplete,
    AnswerCreate,
    AnswerCreated,
    AnswerDetail,
    AnswerOut,
    CodeRunIn,
    CodeSubmissionIn,
    EventsAccepted,
    EventsBatch,
    InterviewEventOut,
    InterviewState,
    RevealOut,
    StartRequest,
)
from leonit.interviews.service import (
    UPLOAD_CHUNK_MAX_BYTES,
    InterviewRoomService,
    code_runner_out,
    public_question,
)

room_router = APIRouter(prefix="/public/invitations/{token}", tags=["interview-room"])
staff_router = APIRouter(prefix="/interviews", tags=["interviews"])


def _limit(request: Request) -> None:
    decision = public_rate_limiter.check(_client_ip(request))
    if not decision.allowed:
        raise HTTPException(status_code=429, detail="Слишком много запросов, попробуйте позже")


def answer_out(answer: Answer) -> AnswerOut:
    return AnswerOut(
        id=str(answer.id),
        question_index=answer.question_index,
        attempt=answer.attempt,
        is_final=answer.is_final,
        status=answer.status.value,  # type: ignore[arg-type]
        upload_offset=answer.upload_offset,
        media_size=answer.media_size,
        duration_ms=answer.duration_ms,
        recording_started_at=aware(answer.recording_started_at),  # type: ignore[arg-type]
        recording_ended_at=aware(answer.recording_ended_at),
        code_submission=code_submission_out(answer.code_submission),
    )


def _state(interview: Interview, answers: list[Answer], revealed) -> InterviewState:
    snapshot = interview.question_snapshot or []
    visible = snapshot[: interview.current_question_index + 1]
    return InterviewState(
        status=interview.status.value,
        current_question_index=interview.current_question_index,
        total_questions=len(snapshot),
        questions=[public_question(item) for item in visible],
        answers=[answer_out(a) for a in answers],
        settings=interview.settings_snapshot or {},
        revealed_at=revealed,
        expires_at=aware(interview.expires_at),  # type: ignore[arg-type]
        code_runner=code_runner_out(),
    )


# --------------------------------------------------------------------- public


@room_router.post("/start", response_model=InterviewState)
async def start_interview(
    token: str, payload: StartRequest, session: DbSession, request: Request
) -> InterviewState:
    _limit(request)
    service = InterviewRoomService(session)
    await service.start(token, payload.client_info)
    return _state(*await service.state(token))


@room_router.get("/state", response_model=InterviewState)
async def interview_state(token: str, session: DbSession, request: Request) -> InterviewState:
    _limit(request)
    return _state(*await InterviewRoomService(session).state(token))


@room_router.post("/questions/{index}/reveal", response_model=RevealOut)
async def reveal_question(
    token: str, index: int, session: DbSession, request: Request
) -> RevealOut:
    _limit(request)
    revealed = await InterviewRoomService(session).reveal(token, index)
    return RevealOut(
        question=public_question(revealed.question),
        revealed_at=aware(revealed.revealed_at),  # type: ignore[arg-type]
        audio_url=revealed.audio_url,
        audio_content_type=revealed.audio_content_type,
        avatar=revealed.avatar,
    )


@room_router.post(
    "/questions/{index}/answers", response_model=AnswerCreated, status_code=status.HTTP_201_CREATED
)
async def create_answer(
    token: str, index: int, payload: AnswerCreate, session: DbSession, request: Request
) -> AnswerCreated:
    _limit(request)
    answer = await InterviewRoomService(session).create_answer(token, index, payload.mime_type)
    return AnswerCreated(answer=answer_out(answer), upload_chunk_max_bytes=UPLOAD_CHUNK_MAX_BYTES)


@room_router.patch("/answers/{answer_id}/chunks", response_model=AnswerOut)
async def upload_chunk(
    token: str,
    answer_id: UUID,
    request: Request,
    session: DbSession,
    upload_offset: Annotated[int | None, Header(alias="Upload-Offset")] = None,
) -> AnswerOut:
    """Докачка по смещению: тело — сырые байты, Upload-Offset — сколько уже принято.

    Повтор потерянного запроса безопасен: хранилище отвергает кусок с чужим
    смещением и сообщает фактический размер (409 + Upload-Offset).
    """
    if upload_offset is None or upload_offset < 0:
        raise ValidationFailedError("Нужен заголовок Upload-Offset")
    data = await request.body()
    try:
        answer = await InterviewRoomService(session).append_chunk(
            token, answer_id, upload_offset, data
        )
    except StorageOffsetConflict as conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=conflict.detail,
            headers={"Upload-Offset": str(conflict.current_size)},
        ) from conflict
    return answer_out(answer)


@room_router.post("/answers/{answer_id}/complete", response_model=AnswerOut)
async def complete_answer(
    token: str, answer_id: UUID, payload: AnswerComplete, session: DbSession, request: Request
) -> AnswerOut:
    _limit(request)
    return answer_out(
        await InterviewRoomService(session).complete_answer(token, answer_id, payload)
    )


@room_router.put("/answers/{question_id}/code", response_model=AnswerOut)
async def save_code(
    token: str, question_id: str, payload: CodeSubmissionIn, session: DbSession
) -> AnswerOut:
    """Черновик (``submit=false``) или отправка кода на текущий вопрос ``kind=code``.

    Без общего лимитера, как и докачка чанков: автосохранение черновика шлёт
    запросы чаще, чем кандидат нажимает кнопки; размер тела ограничен схемой.
    """
    return answer_out(await InterviewRoomService(session).save_code(token, question_id, payload))


@room_router.post("/answers/{question_id}/code/run", response_model=AnswerOut)
async def run_code(
    token: str, question_id: str, payload: CodeRunIn, session: DbSession, request: Request
) -> AnswerOut:
    """Запустить код; при выключенном раннере — 409 с ``code=runner_disabled``."""
    _limit(request)
    return answer_out(await InterviewRoomService(session).run_code(token, question_id, payload))


@room_router.post("/next", response_model=InterviewState)
async def next_question(token: str, session: DbSession, request: Request) -> InterviewState:
    _limit(request)
    service = InterviewRoomService(session)
    await service.next_question(token)
    return _state(*await service.state(token))


@room_router.post("/events", response_model=EventsAccepted)
async def record_events(
    token: str, payload: EventsBatch, session: DbSession, request: Request
) -> EventsAccepted:
    accepted, ignored = await InterviewRoomService(session).record_events(token, payload.events)
    return EventsAccepted(accepted=accepted, ignored=ignored)


# ---------------------------------------------------------------------- staff


@staff_router.get("/{interview_id}/answers", response_model=list[AnswerDetail])
async def interview_answers(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> list[AnswerDetail]:
    service = InterviewRoomService(session)
    interview, answers = await service.answers_for_staff(actor, interview_id)
    snapshot = {item["index"]: item for item in interview.question_snapshot or []}
    return [
        AnswerDetail(
            **answer_out(answer).model_dump(),
            media_url=service.media_url(answer),
            audio_url=service.audio_url(answer),
            media_content_type=answer.media_content_type,
            transcript_text=report_transcript(answer),
            transcript_segments=answer.transcript_segments,
            processing_error=answer.processing_error,
            question_text=(snapshot.get(answer.question_index) or {}).get("text"),
            question_id=answer.question_id,
            parent_answer_id=str(answer.parent_answer_id) if answer.parent_answer_id else None,
        )
        for answer in answers
    ]


@staff_router.get("/{interview_id}/events", response_model=list[InterviewEventOut])
async def interview_events(
    interview_id: UUID, actor: CurrentActor, session: DbSession
) -> list[InterviewEventOut]:
    events = await InterviewRoomService(session).events_for_staff(actor, interview_id)
    return [
        InterviewEventOut(
            id=str(event.id),
            kind=event.kind,
            source=event.source,
            question_index=event.question_index,
            answer_id=str(event.answer_id) if event.answer_id else None,
            at_client_ms=event.at_client_ms,
            at_server=aware(event.at_server),  # type: ignore[arg-type]
            payload=event.payload,
        )
        for event in events
    ]


def _unused(_: InterviewEvent) -> None:  # pragma: no cover - для импорта типов
    pass
