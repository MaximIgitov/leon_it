"""Структурированный ответ модели с валидацией pydantic.

Заключение по кандидату должно быть машиночитаемым: рекомендация выводится из
баллов детерминированно, цитаты привязываются к таймкодам. Поэтому модель
просят вернуть JSON по схеме, ответ проверяет pydantic, а при нарушении схемы
модель получает текст ошибки и один шанс исправиться — этого хватает в
подавляющем большинстве случаев, а бесконечные ретраи скрывали бы проблемы
промпта.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from leonit.ai.providers.base import LLMProvider, Message, ProviderResponseError

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def extract_json(content: str) -> Any:
    """Разобрать JSON из ответа модели, срезав ```json-ограждение и пояснения вокруг."""
    text = content.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    # Модель могла приписать фразу до или после JSON: берём внешний объект.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    raise ValueError("response is not valid JSON")


def _with_schema_instruction(messages: list[Message], schema: dict[str, Any]) -> list[Message]:
    instruction = (
        "Ответь строго одним JSON-объектом без пояснений и без markdown-ограждений. "
        "Объект должен соответствовать JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
    )
    result = [dict(message) for message in messages]
    if result and result[0].get("role") == "system" and isinstance(result[0].get("content"), str):
        result[0]["content"] = f"{result[0]['content']}\n\n{instruction}"
    else:
        result.insert(0, {"role": "system", "content": instruction})
    return result


def _repair_messages(messages: list[Message], content: str | None, error: str) -> list[Message]:
    return [
        *messages,
        {"role": "assistant", "content": content or ""},
        {
            "role": "user",
            "content": (
                "Ответ не прошёл проверку по схеме:\n"
                f"{error}\n\n"
                "Верни исправленный JSON-объект по той же схеме целиком, "
                "без пояснений и без markdown."
            ),
        },
    ]


async def complete_structured[ModelT: BaseModel](
    llm: LLMProvider,
    messages: list[Message],
    schema: type[ModelT],
    *,
    max_repairs: int = 1,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[ModelT, dict[str, Any]]:
    """Получить экземпляр ``schema`` и сырой ответ провайдера (для сохранения)."""
    json_schema = schema.model_json_schema()
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": False},
    }
    conversation = _with_schema_instruction(messages, json_schema)
    last_error = ""
    for attempt in range(max_repairs + 1):
        response = await llm.chat(
            conversation,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.content
        try:
            if not content:
                raise ValueError("empty response")
            parsed = schema.model_validate(extract_json(content))
        except (ValueError, ValidationError) as error:
            last_error = _describe(error)
            if attempt >= max_repairs:
                break
            conversation = _repair_messages(conversation, content, last_error)
            continue
        raw = dict(response.raw)
        raw.setdefault("content", content)
        raw["structured_attempts"] = attempt + 1
        return parsed, raw
    raise ProviderResponseError(
        f"{llm.role}: structured response failed validation after "
        f"{max_repairs + 1} attempt(s): {last_error}"
    )


def _describe(error: Exception) -> str:
    if isinstance(error, ValidationError):
        lines = []
        for item in error.errors()[:10]:
            location = ".".join(str(part) for part in item.get("loc", ())) or "<root>"
            lines.append(f"{location}: {item.get('msg')}")
        return "\n".join(lines)
    return str(error)
