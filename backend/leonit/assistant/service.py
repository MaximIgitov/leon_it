"""Треды ассистента: создание, список, архив, история."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.assistant.models import AssistantMessage, AssistantThread
from leonit.assistant.schemas import ThreadCreate
from leonit.core.authz import Actor, authorize
from leonit.core.errors import ConflictError, NotFoundError
from leonit.core.time import utcnow


class AssistantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_thread(self, actor: Actor, payload: ThreadCreate) -> AssistantThread:
        authorize(actor, "assistant.use")
        thread = AssistantThread(
            organization_id=actor.organization_id,
            user_id=actor.user.id,
            title=payload.title.strip(),
            page_path=payload.page_path,
        )
        self.session.add(thread)
        await self.session.commit()
        return thread

    async def list_threads(self, actor: Actor, *, limit: int = 50) -> list[AssistantThread]:
        authorize(actor, "assistant.use")
        rows = await self.session.scalars(
            select(AssistantThread)
            .where(
                AssistantThread.user_id == actor.user.id,
                AssistantThread.organization_id == actor.organization_id,
                AssistantThread.archived_at.is_(None),
            )
            .order_by(AssistantThread.updated_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def get_thread(self, actor: Actor, thread_id: UUID) -> AssistantThread:
        authorize(actor, "assistant.use")
        thread = await self.session.get(AssistantThread, thread_id)
        # Чужой тред — «не найден», а не «запрещён»: не раскрываем его существование.
        if (
            thread is None
            or thread.user_id != actor.user.id
            or thread.organization_id != actor.organization_id
        ):
            raise NotFoundError("Чат не найден")
        return thread

    async def writable_thread(self, actor: Actor, thread_id: UUID) -> AssistantThread:
        thread = await self.get_thread(actor, thread_id)
        if thread.archived_at is not None:
            raise ConflictError("Чат в архиве — начните новый")
        return thread

    async def archive_thread(self, actor: Actor, thread_id: UUID) -> AssistantThread:
        thread = await self.get_thread(actor, thread_id)
        if thread.archived_at is None:
            thread.archived_at = utcnow()
            await self.session.commit()
        return thread

    async def list_messages(self, actor: Actor, thread_id: UUID) -> list[AssistantMessage]:
        thread = await self.get_thread(actor, thread_id)
        rows = await self.session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.thread_id == thread.id)
            .order_by(AssistantMessage.created_at.asc(), AssistantMessage.id.asc())
        )
        return list(rows)
