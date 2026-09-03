"""Детерминированный провайдер без сети.

Нужен для CI, e2e и локальной разработки без ключей: ответы предсказуемы,
чтобы тесты могли утверждать конкретные значения, и «осмысленны» настолько,
чтобы конвейер (структурированное заключение, tool-вызовы ассистента, озвучка
вопроса) проходил насквозь.
"""

from __future__ import annotations

import io
import json
import re
import wave
from collections.abc import AsyncIterator
from typing import Any

from leonit.ai.config import RoleConfig
from leonit.ai.providers.base import (
    AudioResult,
    LLMDelta,
    LLMProvider,
    LLMResponse,
    Message,
    STTProvider,
    ToolCall,
    ToolCallDelta,
    Transcript,
    TranscriptSegment,
    TTSProvider,
    Usage,
)

_TOOL_CALL_RE = re.compile(r"\[\[call:([\w.\-]+)\s*(\{.*?\})?\s*\]\]", re.DOTALL)
_SIDECAR_PREFIX = "sidecar:"
_MAX_DEPTH = 8

_STRING_FORMATS: dict[str, str] = {
    "date-time": "2026-01-01T12:00:00Z",
    "date": "2026-01-01",
    "time": "12:00:00",
    "email": "fake@example.com",
    "uuid": "00000000-0000-4000-8000-000000000000",
    "uri": "https://example.com/fake",
    "url": "https://example.com/fake",
}


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    node: Any = root
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return {}
        node = node[part]
    return node if isinstance(node, dict) else {}


def _number(schema: dict[str, Any], *, integer: bool) -> int | float:
    low = schema.get("minimum", schema.get("exclusiveMinimum"))
    high = schema.get("maximum", schema.get("exclusiveMaximum"))
    if low is not None and high is not None:
        value: float = (float(low) + float(high)) / 2
    elif low is not None:
        value = max(3.0, float(low) + (1 if "exclusiveMinimum" in schema else 0))
    elif high is not None:
        value = min(3.0, float(high) - (1 if "exclusiveMaximum" in schema else 0))
    else:
        value = 3.0
    return int(value) if integer else value


def fake_value_for_schema(
    schema: dict[str, Any],
    *,
    name: str = "value",
    root: dict[str, Any] | None = None,
    depth: int = 0,
) -> Any:
    """Сгенерировать значение по JSON Schema (pydantic ``model_json_schema``)."""
    root = root if root is not None else schema
    if depth > _MAX_DEPTH:
        return None
    if "$ref" in schema:
        overrides = {key: value for key, value in schema.items() if key != "$ref"}
        merged = {**_resolve_ref(schema["$ref"], root), **overrides}
        return fake_value_for_schema(merged, name=name, root=root, depth=depth + 1)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for combinator in ("anyOf", "oneOf", "allOf"):
        options = schema.get(combinator)
        if options:
            candidates = [o for o in options if o.get("type") != "null"] or options
            return fake_value_for_schema(candidates[0], name=name, root=root, depth=depth + 1)

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind is None:
        kind = "object" if "properties" in schema else "string"

    if kind == "null":
        return None
    if kind == "boolean":
        return True
    if kind == "integer":
        return _number(schema, integer=True)
    if kind == "number":
        return _number(schema, integer=False)
    if kind == "string":
        value = _STRING_FORMATS.get(schema.get("format", ""), f"fake {name}")
        min_length = int(schema.get("minLength") or 0)
        if len(value) < min_length:
            value = (value + " ") * (min_length // (len(value) + 1) + 1)
        max_length = schema.get("maxLength")
        return value[: int(max_length)] if max_length is not None else value
    if kind == "array":
        items = schema.get("items") or {}
        count = max(2, int(schema.get("minItems") or 0))
        if schema.get("maxItems") is not None:
            count = min(count, int(schema["maxItems"]))
        return [
            fake_value_for_schema(items, name=f"{name} {i + 1}", root=root, depth=depth + 1)
            for i in range(count)
        ]
    if kind == "object":
        properties = schema.get("properties") or {}
        return {
            key: fake_value_for_schema(sub, name=key, root=root, depth=depth + 1)
            for key, sub in properties.items()
        }
    return f"fake {name}"


def _message_text(message: Message) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("text")
        )
    return ""


def _last_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _message_text(message)
    return ""


def _usage(prompt: str, completion: str) -> Usage:
    prompt_tokens, completion_tokens = len(prompt) // 4, len(completion) // 4
    return Usage(prompt_tokens, completion_tokens, prompt_tokens + completion_tokens)


class FakeLLM(LLMProvider):
    def __init__(self, config: RoleConfig) -> None:
        self.config = config
        self.role = config.role
        self.model = config.model

    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        user_text = _last_user_text(messages)
        prompt_text = "\n".join(_message_text(m) for m in messages)
        raw: dict[str, Any] = {"provider": "fake", "model": self.model, "role": self.role}

        if tools:
            match = _TOOL_CALL_RE.search(user_text)
            if match:
                arguments = match.group(2) or "{}"
                json.loads(arguments)  # заранее ловим кривой JSON в тесте, а не в обработчике
                call = ToolCall(id="call_fake_1", name=match.group(1), arguments=arguments)
                raw["tool_calls"] = [{"id": call.id, "name": call.name, "arguments": arguments}]
                return LLMResponse(
                    content=None,
                    tool_calls=[call],
                    raw=raw,
                    usage=_usage(prompt_text, arguments),
                    finish_reason="tool_calls",
                )

        if response_format:
            kind = response_format.get("type")
            if kind == "json_schema":
                schema = (response_format.get("json_schema") or {}).get("schema") or {}
                value = fake_value_for_schema(schema)
            elif kind == "json_object":
                value = {"content": f"[fake {self.role}] {user_text}"}
            else:
                value = None
            if value is not None:
                content = json.dumps(value, ensure_ascii=False)
                raw["content"] = content
                return LLMResponse(
                    content=content,
                    raw=raw,
                    usage=_usage(prompt_text, content),
                    finish_reason="stop",
                )

        content = f"[fake {self.role}] {user_text}" if user_text else f"[fake {self.role}]"
        raw["content"] = content
        return LLMResponse(
            content=content, raw=raw, usage=_usage(prompt_text, content), finish_reason="stop"
        )

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LLMDelta]:
        response = await self.chat(
            messages, tools=tools, temperature=temperature, max_tokens=max_tokens
        )
        if response.tool_calls:
            call = response.tool_calls[0]
            half = len(call.arguments) // 2
            yield LLMDelta(tool_calls_delta=[ToolCallDelta(index=0, id=call.id, name=call.name)])
            yield LLMDelta(
                tool_calls_delta=[ToolCallDelta(index=0, arguments=call.arguments[:half])]
            )
            yield LLMDelta(
                tool_calls_delta=[ToolCallDelta(index=0, arguments=call.arguments[half:])],
                finish_reason="tool_calls",
            )
            return
        for index, piece in enumerate(_split_in_three(response.content or "")):
            yield LLMDelta(content=piece, finish_reason="stop" if index == 2 else None)


def _split_in_three(text: str) -> list[str]:
    third = max(1, (len(text) + 2) // 3)
    parts = [text[:third], text[third : 2 * third], text[2 * third :]]
    return parts


class FakeSTT(STTProvider):
    def __init__(self, config: RoleConfig) -> None:
        self.config = config
        self.model = config.model

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str = "ru",
        prompt: str | None = None,
    ) -> Transcript:
        if content_type.split(";", 1)[0].strip().lower().startswith("text/"):
            text = audio.decode("utf-8", errors="replace").strip()
        elif prompt and prompt.startswith(_SIDECAR_PREFIX):
            # Сайдкар: e2e-тесты кладут «ожидаемый» текст рядом с записью, чтобы
            # проверять оценку на осмысленном транскрипте без реального STT.
            text = prompt[len(_SIDECAR_PREFIX) :].strip()
        else:
            text = f"(фейковая транскрипция {len(audio)} байт)"
        # 2.5 слова в секунду — правдоподобная длительность для таймкодов цитат.
        duration = round(max(1.0, len(text.split()) / 2.5), 2)
        segments = [TranscriptSegment(start_s=0.0, end_s=duration, text=text)] if text else []
        return Transcript(
            text=text,
            segments=segments,
            language=language,
            raw={"provider": "fake", "model": self.model, "bytes": len(audio)},
        )


def silence_wav(seconds: float = 1.0, *, sample_rate: int = 16_000) -> bytes:
    """Валидный WAV с тишиной: моно, 16 бит."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return buffer.getvalue()


_SILENCE_1S = silence_wav(1.0)


class FakeTTS(TTSProvider):
    def __init__(self, config: RoleConfig) -> None:
        self.config = config
        self.model = config.model

    def resolve_format(self, audio_format: str) -> str:
        return "wav"

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        audio_format: str = "mp3",
    ) -> AudioResult:
        return AudioResult(data=_SILENCE_1S, content_type="audio/wav")
