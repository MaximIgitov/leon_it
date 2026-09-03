"""Треды и сообщения ассистента.

Тред принадлежит пользователю, а не организации: чат — личный черновик мыслей
рекрутера, и коллеги его не видят. Сообщения с ролью ``tool`` хранятся вместе
с результатом вызова, чтобы история воспроизводилась для модели в том же виде,
в каком она её видела, а карточки действий восстанавливались после перезагрузки.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leonit.core.db import Base, TimestampMixin, uuid_pk
from leonit.core.time import utcnow


class AssistantMessageRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class AssistantThread(TimestampMixin, Base):
    __tablename__ = "assistant_threads"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Адрес страницы, с которой начат чат: подсказка модели, не источник истины.
    page_path: Mapped[str | None] = mapped_column(String(512))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[AssistantMessage]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.position",
    )


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assistant_threads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[AssistantMessageRole] = mapped_column(
        Enum(AssistantMessageRole, name="assistant_message_role", native_enum=False, length=16),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Выполненные и предложенные действия: [{kind, tool, params, summary, ...}].
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # Порядок в треде. Сообщения одного хода пишутся за миллисекунды, и
    # created_at у них совпадает (на Windows часы идут с шагом ~15 мс), а
    # случайный uuid как tie-break перемешивал бы историю для модели.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    thread: Mapped[AssistantThread] = relationship(back_populates="messages")
