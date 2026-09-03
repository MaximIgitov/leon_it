"""Цикл агента: модель ↔ инструменты ↔ события для клиента.

Ход пользователя — это до ``ASSISTANT_MAX_STEPS`` обращений к модели: каждое
либо заканчивается текстом (ход завершён), либо tool-вызовами, результаты
которых возвращаются в диалог как JSON внутри секции данных (см.
``leonit.assistant.prompts``). Клиент получает события по мере появления:
``token`` — кусок текста, ``action`` — выполненный или предложенный
инструмент, ``reset`` — текст до tool-вызова отброшен (модель «передумала»),
``done`` — итоговое сообщение, ``error`` — ход прерван.

Всё, что модель узнаёт о странице, — только её адрес: он полезен как подсказка
(«открыта вакансия X»), но не заменяет проверку через инструменты.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.ai.gateway import get_llm
from leonit.ai.providers.base import (
    LLMDelta,
    LLMProvider,
    Message,
    ProviderError,
    StreamAccumulator,
    ToolCallDelta,
)
from leonit.assistant.models import AssistantMessage, AssistantMessageRole, AssistantThread
from leonit.assistant.prompts import build_system_prompt
from leonit.assistant.toolbox import ServiceToolbox, ToolResult
from leonit.core.authz import Actor
from leonit.core.config import get_settings
from leonit.core.logging import get_logger
from leonit.core.time import utcnow

log = get_logger(__name__)


def history_messages(rows: list[AssistantMessage], *, tool_limit: int = 4000) -> list[Message]:
    """История треда в формате модели; tool-сообщения — парой assistant+tool."""
    out: list[Message] = []
    for row in rows:
        if row.role == AssistantMessageRole.user:
            out.append({"role": "user", "content": row.content})
        elif row.role == AssistantMessageRole.assistant:
            out.append({"role": "assistant", "content": row.content or ""})
        else:
            action = row.actions[0] if row.actions else {}
            call_id = str(action.get("tool_call_id") or f"call_{row.id.hex[:12]}")
            name = str(action.get("tool") or "tool")
            out.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": _json(action.get("params") or {}),
                            },
                        }
                    ],
                }
            )
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": row.content[:tool_limit],
                }
            )
    return out


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass(slots=True)
class AssistantEvent:
    type: str
    data: dict[str, Any]


def message_payload(message: AssistantMessage) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "role": message.role.value,
        "content": message.content,
        "actions": [
            {key: value for key, value in action.items() if key != "tool_call_id"}
            for action in message.actions
        ],
        "created_at": message.created_at.isoformat(),
    }


class AssistantRunner:
    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        *,
        llm: LLMProvider | None = None,
        toolbox: ServiceToolbox | None = None,
        max_steps: int | None = None,
        history_limit: int | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.actor = actor
        self.llm = llm or get_llm("assistant")
        self.toolbox = toolbox or ServiceToolbox(session, actor, llm=self.llm)
        self.max_steps = max_steps or settings.ASSISTANT_MAX_STEPS
        self.history_limit = history_limit or settings.ASSISTANT_HISTORY_LIMIT

    async def run(
        self, thread: AssistantThread, content: str, page_path: str | None
    ) -> AsyncIterator[AssistantEvent]:
        # id запоминаем сразу: откат после ошибки инструмента «протухает» тред,
        # а лезть за атрибутом в базу из-под синхронного кода нельзя.
        thread_id = thread.id
        history = await self._history(thread_id)
        position = await self._next_position(thread_id)
        if page_path:
            thread.page_path = page_path
        if not thread.title.strip():
            thread.title = _title_from(content)
        user_message = AssistantMessage(
            thread_id=thread_id,
            role=AssistantMessageRole.user,
            content=content,
            position=position,
        )
        self.session.add(user_message)
        await self.session.commit()
        yield AssistantEvent("user", {"message": message_payload(user_message)})

        conversation: list[Message] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.actor, self.toolbox.descriptions(), thread.page_path
                ),
            },
            *history_messages(history),
            {"role": "user", "content": content},
        ]
        specs = self.toolbox.specs()
        actions: list[dict[str, Any]] = []
        final_text = ""
        try:
            for _step in range(self.max_steps):
                accumulator = StreamAccumulator()
                streamed = False
                async for delta in self._step(conversation, specs):
                    accumulator.add(delta)
                    if delta.content:
                        streamed = True
                        yield AssistantEvent("token", {"text": delta.content})
                response = accumulator.response()
                if not response.tool_calls:
                    final_text = response.content or ""
                    break
                if streamed:
                    # Модель начала отвечать текстом, а потом решила вызвать
                    # инструмент: черновик клиент отбрасывает, итог придёт после.
                    yield AssistantEvent("reset", {})
                conversation.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {"name": call.name, "arguments": call.arguments},
                            }
                            for call in response.tool_calls
                        ],
                    }
                )
                for call in response.tool_calls:
                    result = await self._execute(call.name, call.arguments)
                    action = result.as_action()
                    actions.append(action)
                    # Результат уходит модели и в историю в одном и том же виде —
                    # как секция данных, а не как текст, которому можно верить.
                    model_text = result.for_model()
                    position += 1
                    self.session.add(
                        AssistantMessage(
                            thread_id=thread_id,
                            role=AssistantMessageRole.tool,
                            content=model_text,
                            actions=[{**action, "tool_call_id": call.id}],
                            position=position,
                        )
                    )
                    await self.session.commit()
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": model_text,
                        }
                    )
                    yield AssistantEvent("action", action)
            else:
                # Лимит шагов: просим подвести итог без инструментов, чтобы
                # пользователь получил хоть какой-то ответ, а не тишину.
                response = await self.llm.chat(conversation)
                final_text = (
                    response.content or "Не удалось завершить задачу за отведённое число шагов."
                )
                yield AssistantEvent("token", {"text": final_text})
        except ProviderError as error:
            log.warning("assistant.provider_error thread=%s error=%s", thread_id, error)
            failure = f"Не удалось получить ответ модели: {error.detail}"
            message = await self._finish(thread, failure, actions, position + 1)
            yield AssistantEvent(
                "error",
                {
                    "detail": error.detail,
                    "message": message_payload(message),
                    "thread": {"id": str(thread_id), "title": thread.title},
                },
            )
            return
        except Exception:
            log.exception("assistant.run_failed thread=%s", thread_id)
            failure = "Внутренняя ошибка ассистента, попробуйте ещё раз"
            message = await self._finish(thread, failure, actions, position + 1)
            yield AssistantEvent(
                "error",
                {
                    "detail": failure,
                    "message": message_payload(message),
                    "thread": {"id": str(thread_id), "title": thread.title},
                },
            )
            return
        message = await self._finish(thread, final_text, actions, position + 1)
        yield AssistantEvent(
            "done",
            {
                "message": message_payload(message),
                "thread": {"id": str(thread_id), "title": thread.title},
            },
        )

    # ------------------------------------------------------------ внутренние

    async def _history(self, thread_id) -> list[AssistantMessage]:
        rows = await self.session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.thread_id == thread_id)
            .order_by(
                AssistantMessage.position.desc(),
                AssistantMessage.created_at.desc(),
                AssistantMessage.id.desc(),
            )
            .limit(self.history_limit)
        )
        return list(reversed(list(rows)))

    async def _next_position(self, thread_id) -> int:
        current = await self.session.scalar(
            select(func.max(AssistantMessage.position)).where(
                AssistantMessage.thread_id == thread_id
            )
        )
        return int(current or 0) + 1

    async def _step(
        self, conversation: list[Message], specs: list[dict[str, Any]]
    ) -> AsyncIterator[LLMDelta]:
        """Стрим, если провайдер умеет; иначе обычный ответ одним куском."""
        received = False
        try:
            async for delta in self.llm.stream_chat(conversation, tools=specs or None):
                received = True
                yield delta
        except NotImplementedError:
            if received:
                raise
            response = await self.llm.chat(conversation, tools=specs or None)
            yield LLMDelta(
                content=response.content,
                tool_calls_delta=[
                    ToolCallDelta(index=i, id=call.id, name=call.name, arguments=call.arguments)
                    for i, call in enumerate(response.tool_calls)
                ]
                or None,
                finish_reason=response.finish_reason,
            )

    async def _execute(self, name: str, arguments: str) -> ToolResult:
        try:
            parsed = json.loads(arguments or "{}")
        except ValueError:
            return ToolResult("error", name, {}, "Некорректный JSON в аргументах инструмента")
        if not isinstance(parsed, dict):
            return ToolResult("error", name, {}, "Аргументы инструмента должны быть объектом")
        return await self.toolbox.call(name, parsed)

    async def _finish(
        self,
        thread: AssistantThread,
        content: str,
        actions: list[dict[str, Any]],
        position: int,
    ) -> AssistantMessage:
        # Ошибка инструмента откатывает транзакцию и «протухает» объекты сессии;
        # перечитываем тред явно, чтобы обращение к атрибутам не полезло в базу
        # из синхронного кода.
        await self.session.refresh(thread)
        message = AssistantMessage(
            thread_id=thread.id,
            role=AssistantMessageRole.assistant,
            content=content,
            actions=actions,
            position=position,
        )
        self.session.add(message)
        thread.updated_at = utcnow()
        await self.session.commit()
        return message


def _title_from(content: str) -> str:
    line = " ".join(content.split())
    return line if len(line) <= 60 else line[:57].rstrip() + "…"
