"""Абстракции провайдеров и общие типы ответов.

Сообщения передаются в формате OpenAI (``{"role": ..., "content": ...}``):
это де-факто стандарт агрегаторов, и переводить в собственный формат и обратно
значило бы поддерживать два набора крайних случаев (tool-вызовы, мультимодальные
части) без выгоды.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from leonit.core.errors import UpstreamError

Message = dict[str, Any]

# Соответствие формата озвучки типу содержимого: провайдер отдаёт «сырые» байты,
# а отдавать их браузеру и класть в кэш нужно с правильным Content-Type.
AUDIO_CONTENT_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "pcm": "audio/pcm",
}


class ProviderError(UpstreamError):
    """Общий предок ошибок шлюза; наружу отображается как 502."""


class ProviderConfigurationError(ProviderError):
    """Провайдер не настроен или отверг настройки: нет ключа, оплаты, модели."""


class ProviderUnavailableError(ProviderError):
    """Провайдер временно недоступен: сеть, таймауты, 5xx, открытый breaker."""


class ProviderResponseError(ProviderError):
    """Провайдер ответил, но ответ непригоден: 4xx, не JSON, не по схеме."""

    def __init__(
        self,
        detail: str,
        *,
        upstream_status: int | None = None,
        upstream_message: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.upstream_status = upstream_status
        # Текст ошибки провайдера отдельно от нашего detail: по нему решается,
        # относится ли отказ к формату ответа (тогда уместен фолбэк) или нет.
        self.upstream_message = upstream_message


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str

    def arguments_json(self) -> Any:
        return json.loads(self.arguments or "{}")


@dataclass(slots=True)
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    usage: Usage | None = None
    finish_reason: str | None = None


@dataclass(slots=True)
class ToolCallDelta:
    """Кусочек tool-вызова из стрима: аргументы приходят фрагментами по ``index``."""

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""


@dataclass(slots=True)
class LLMDelta:
    content: str | None = None
    tool_calls_delta: list[ToolCallDelta] | None = None
    finish_reason: str | None = None
    usage: Usage | None = None


class StreamAccumulator:
    """Собирает дельты стрима в полный ``LLMResponse`` (аргументы — по index)."""

    def __init__(self) -> None:
        self._content: list[str] = []
        self._calls: dict[int, ToolCallDelta] = {}
        self.finish_reason: str | None = None
        self.usage: Usage | None = None

    def add(self, delta: LLMDelta) -> None:
        if delta.content:
            self._content.append(delta.content)
        for part in delta.tool_calls_delta or ():
            current = self._calls.get(part.index)
            if current is None:
                self._calls[part.index] = ToolCallDelta(
                    index=part.index, id=part.id, name=part.name, arguments=part.arguments
                )
                continue
            current.id = current.id or part.id
            current.name = current.name or part.name
            current.arguments += part.arguments
        if delta.finish_reason:
            self.finish_reason = delta.finish_reason
        if delta.usage:
            self.usage = delta.usage

    @property
    def content(self) -> str:
        return "".join(self._content)

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [
            ToolCall(id=part.id or f"call_{index}", name=part.name or "", arguments=part.arguments)
            for index, part in sorted(self._calls.items())
        ]

    def response(self) -> LLMResponse:
        return LLMResponse(
            content=self.content or None,
            tool_calls=self.tool_calls,
            raw={"stream": True},
            usage=self.usage,
            finish_reason=self.finish_reason,
        )


@dataclass(slots=True)
class TranscriptSegment:
    start_s: float
    end_s: float
    text: str


@dataclass(slots=True)
class Transcript:
    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AudioResult:
    data: bytes
    content_type: str


class LLMProvider(ABC):
    role: str
    model: str

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    def stream_chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LLMDelta]: ...


class STTProvider(ABC):
    model: str

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str = "ru",
        prompt: str | None = None,
    ) -> Transcript: ...


class TTSProvider(ABC):
    model: str
    default_voice: str = "alloy"

    def resolve_format(self, audio_format: str) -> str:
        """Какой формат реально вернёт провайдер (фейк всегда отдаёт WAV)."""
        return audio_format

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        audio_format: str = "mp3",
    ) -> AudioResult: ...
