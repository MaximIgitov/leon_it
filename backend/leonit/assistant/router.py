from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from leonit.accounts.deps import CurrentActor
from leonit.assistant.models import AssistantMessage, AssistantThread
from leonit.assistant.placeholders import placeholders_for
from leonit.assistant.runner import AssistantEvent, AssistantRunner
from leonit.assistant.schemas import (
    ActionOut,
    MessageIn,
    MessageOut,
    PlaceholdersOut,
    SendResult,
    ThreadCreate,
    ThreadOut,
)
from leonit.assistant.service import AssistantService
from leonit.core.authz import Actor, authorize
from leonit.core.db import get_session_maker
from leonit.core.deps import DbSession
from leonit.core.errors import UpstreamError
from leonit.core.logging import get_logger
from leonit.core.time import aware

log = get_logger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


def thread_out(thread: AssistantThread) -> ThreadOut:
    return ThreadOut(
        id=str(thread.id),
        title=thread.title,
        page_path=thread.page_path,
        created_at=aware(thread.created_at),  # type: ignore[arg-type]
        updated_at=aware(thread.updated_at),  # type: ignore[arg-type]
        archived_at=aware(thread.archived_at),
    )


def message_out(message: AssistantMessage) -> MessageOut:
    return MessageOut(
        id=str(message.id),
        role=message.role.value,  # type: ignore[arg-type]
        content=message.content,
        actions=[
            ActionOut(**{key: value for key, value in action.items() if key != "tool_call_id"})
            for action in message.actions
        ],
        created_at=aware(message.created_at),  # type: ignore[arg-type]
    )


@router.get("/placeholders", response_model=PlaceholdersOut)
async def placeholders(actor: CurrentActor) -> PlaceholdersOut:
    authorize(actor, "assistant.use")
    return PlaceholdersOut(role=actor.role.value, items=placeholders_for(actor.role.value))


@router.get("/threads", response_model=list[ThreadOut])
async def list_threads(actor: CurrentActor, session: DbSession) -> list[ThreadOut]:
    return [thread_out(t) for t in await AssistantService(session).list_threads(actor)]


@router.post("/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_thread(
    payload: ThreadCreate, actor: CurrentActor, session: DbSession
) -> ThreadOut:
    return thread_out(await AssistantService(session).create_thread(actor, payload))


@router.get("/threads/{thread_id}", response_model=ThreadOut)
async def get_thread(thread_id: UUID, actor: CurrentActor, session: DbSession) -> ThreadOut:
    return thread_out(await AssistantService(session).get_thread(actor, thread_id))


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_thread(thread_id: UUID, actor: CurrentActor, session: DbSession) -> None:
    await AssistantService(session).archive_thread(actor, thread_id)


@router.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
async def list_messages(
    thread_id: UUID, actor: CurrentActor, session: DbSession
) -> list[MessageOut]:
    return [message_out(m) for m in await AssistantService(session).list_messages(actor, thread_id)]


async def _run(actor: Actor, thread_id: UUID, payload: MessageIn) -> AsyncIterator[AssistantEvent]:
    """Ход агента в собственной сессии.

    Ошибка инструмента откатывает транзакцию, а откат «протухает» все объекты
    сессии, включая пользователя и организацию из ``CurrentActor``. В отдельной
    сессии откат не задевает объекты запроса, а стрим не зависит от того, когда
    FastAPI закроет сессию-зависимость.
    """
    async with get_session_maker()() as session:
        thread = await session.get(AssistantThread, thread_id)
        if thread is None:
            yield AssistantEvent("error", {"detail": "Чат не найден"})
            return
        runner = AssistantRunner(session, actor)
        async for event in runner.run(thread, payload.content, payload.page_path):
            yield event


@router.post("/threads/{thread_id}/messages", response_model=SendResult)
async def send_message(
    thread_id: UUID, payload: MessageIn, actor: CurrentActor, session: DbSession
) -> SendResult:
    """Ответ целиком, без стрима: для интеграций и тестов."""
    service = AssistantService(session)
    thread = await service.writable_thread(actor, thread_id)
    user_message: dict[str, Any] | None = None
    assistant_message: dict[str, Any] | None = None
    async for event in _run(actor, thread.id, payload):
        if event.type == "user":
            user_message = event.data["message"]
        elif event.type == "done":
            assistant_message = event.data["message"]
        elif event.type == "error":
            raise UpstreamError(event.data["detail"])
    assert user_message is not None and assistant_message is not None
    await session.refresh(thread)
    return SendResult(
        thread=thread_out(thread),
        user_message=MessageOut(**user_message),
        assistant_message=MessageOut(**assistant_message),
    )


def _sse(event: AssistantEvent) -> str:
    return f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


@router.post("/threads/{thread_id}/messages/stream")
async def stream_message(
    thread_id: UUID, payload: MessageIn, actor: CurrentActor, session: DbSession
) -> StreamingResponse:
    """Ответ по SSE: события ``user``, ``token``, ``action``, ``reset``, ``done``, ``error``."""
    # Права и существование треда проверяем до начала стрима — иначе 404 уже не отдать.
    await AssistantService(session).writable_thread(actor, thread_id)

    async def events() -> AsyncIterator[str]:
        try:
            async for event in _run(actor, thread_id, payload):
                yield _sse(event)
        except Exception:  # стрим уже начат, статус ответа не сменить
            log.exception("assistant.stream_failed thread=%s", thread_id)
            yield _sse(AssistantEvent("error", {"detail": "Внутренняя ошибка ассистента"}))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
