from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MessageRoleLiteral = Literal["user", "assistant", "tool"]
ActionKindLiteral = Literal["done", "proposed", "error"]


class ThreadCreate(BaseModel):
    title: str = Field(default="", max_length=255)
    page_path: str | None = Field(default=None, max_length=512)


class ThreadOut(BaseModel):
    id: str
    title: str
    page_path: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ActionOut(BaseModel):
    """Карточка действия в ответе: выполнено, предложено или не удалось."""

    kind: ActionKindLiteral
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    # Для kind=done — что вернул инструмент (усечённо), для proposed — что подтвердить.
    result: Any = None
    proposal: dict[str, Any] | None = None


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    # Адрес открытой страницы: обновляется каждым сообщением, пользователь ходит по кабинету.
    page_path: str | None = Field(default=None, max_length=512)


class MessageOut(BaseModel):
    id: str
    role: MessageRoleLiteral
    content: str
    actions: list[ActionOut]
    created_at: datetime


class SendResult(BaseModel):
    thread: ThreadOut
    user_message: MessageOut
    assistant_message: MessageOut


class PlaceholdersOut(BaseModel):
    role: str
    items: list[str]
