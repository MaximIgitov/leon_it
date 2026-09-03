"""Провайдер для OpenAI-совместимых API (OpenAI, AITunnel, OpenRouter, vLLM).

Один HTTP-слой на все три вида запросов: авторизация, ретраи с линейным
бэкоффом на временные ошибки, circuit breaker на роль и перевод HTTP-статусов
в доменные ошибки. Выше него — тонкие обёртки под ``/chat/completions``,
``/audio/transcriptions`` и ``/audio/speech``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from leonit.ai.circuit_breaker import CircuitBreaker
from leonit.ai.config import RoleConfig
from leonit.ai.http_client import get_http_client
from leonit.ai.providers.base import (
    AUDIO_CONTENT_TYPES,
    AudioResult,
    LLMDelta,
    LLMProvider,
    LLMResponse,
    Message,
    ProviderConfigurationError,
    ProviderError,
    ProviderResponseError,
    ProviderUnavailableError,
    STTProvider,
    ToolCall,
    ToolCallDelta,
    Transcript,
    TranscriptSegment,
    TTSProvider,
    Usage,
)

log = logging.getLogger(__name__)

# OpenAI и совместимые агрегаторы принимают файлы до 25 МБ.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
_RETRYABLE_STATUSES = frozenset({408, 429})

_AUDIO_EXTENSIONS: dict[str, str] = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "video/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/flac": ".flac",
}


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_base_s: float = 1.0

    def delay_for(self, attempt: int) -> float:
        # Линейный бэкофф: 1с, 2с, 3с — провайдеры отвечают 429 на секунды, а не
        # минуты, экспонента здесь только тянула бы обработку интервью.
        return self.backoff_base_s * attempt


def _is_retryable(status: int) -> bool:
    return status >= 500 or status in _RETRYABLE_STATUSES


def _message_from_body(body: Any) -> str | None:
    """Достать текст ошибки из тела в любом из ходовых форматов агрегаторов."""
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:300]
    if isinstance(error, str):
        return error[:300]
    if body.get("message"):
        return str(body["message"])[:300]
    return None


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    return _message_from_body(body) or response.text[:300]


def _chunk_error_message(chunk: dict[str, Any]) -> str | None:
    """Ошибка внутри 200-стрима: провайдер уже отдал заголовки, а потом сломался."""
    if "error" not in chunk:
        return None
    return _message_from_body(chunk) or json.dumps(chunk["error"], ensure_ascii=False)[:300]


def _rejects_format(error: ProviderResponseError, *needles: str) -> bool:
    """Отказ 400 именно из-за формата ответа, а не из-за промпта, лимитов или файла.

    Фолбэк на более простой формат уместен только в этом случае: иначе он лишь
    маскирует настоящую ошибку вторым запросом и «запоминает» ложный вывод.
    """
    if error.upstream_status != 400:
        return False
    text = (error.upstream_message or "").lower()
    return any(needle in text for needle in needles)


class OpenAICompatibleClient:
    """HTTP-слой одной роли: ключ, таймаут, ретраи, breaker."""

    def __init__(
        self,
        config: RoleConfig,
        *,
        http: httpx.AsyncClient | None = None,
        retry: RetryPolicy | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self._http = http
        self.retry = retry or RetryPolicy()
        self.breaker = breaker or CircuitBreaker()
        self._sleep = sleep

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = get_http_client(self.config.base_url, self.config.proxy_url)
        return self._http

    def _build(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Request:
        self._require_api_key()
        return self.http.build_request(
            method,
            self.config.base_url + path,
            json=json_body,
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            timeout=httpx.Timeout(self.config.timeout_s, connect=10.0),
        )

    async def request(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._guarded(lambda: self._build("POST", path, **kwargs), stream=False)

    async def request_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.request(path, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            # response_format=text у STT — легитимный не-JSON ответ.
            return {"text": response.text}
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                f"{self.config.role}: unexpected response shape",
                upstream_status=response.status_code,
            )
        return payload

    @asynccontextmanager
    async def stream(self, path: str, **kwargs: Any) -> AsyncIterator[httpx.Response]:
        response = await self._guarded(lambda: self._build("POST", path, **kwargs), stream=True)
        try:
            yield response
        except httpx.TransportError as error:
            # Заголовки пришли, а тело оборвалось: для вызывающего это та же
            # недоступность провайдера, что и обрыв до ответа, и breaker должен
            # её учесть — иначе «умирающий» провайдер с 200-заголовками никогда
            # не откроет контур.
            self.breaker.record_failure()
            raise ProviderUnavailableError(
                f"{self.config.role}: {type(error).__name__} while reading stream from {path}"
            ) from error
        finally:
            await response.aclose()

    async def _guarded(self, build: Callable[[], httpx.Request], *, stream: bool) -> httpx.Response:
        # Без ключа запрос не уйдёт — незачем тратить на него пробный слот breaker.
        self._require_api_key()
        if not self.breaker.allow():
            raise ProviderUnavailableError(
                f"{self.config.role}: circuit breaker is open, provider considered down"
            )
        try:
            response = await self._send_with_retries(build, stream=stream)
        except ProviderUnavailableError:
            self.breaker.record_failure()
            raise
        except ProviderError:
            # 4xx — провайдер жив и отвечает, просто отверг запрос: для контура
            # это успех. Иначе пробный запрос в half_open, упавший на 400/401/404,
            # не закрывал бы и не открывал контур, а слот оставался бы занят.
            self.breaker.record_success()
            raise
        except BaseException:
            # Отмена или чужое исключение: о состоянии провайдера ничего не
            # известно, возвращаем слот пробного запроса.
            self.breaker.release_probe()
            raise
        self.breaker.record_success()
        return response

    def _require_api_key(self) -> None:
        if not self.config.api_key:
            role = self.config.role.upper()
            raise ProviderConfigurationError(
                f"{self.config.role}: API key is not set "
                f"(MODEL_{role}_API_KEY or MODEL_DEFAULT_API_KEY)"
            )

    async def _send_with_retries(
        self, build: Callable[[], httpx.Request], *, stream: bool
    ) -> httpx.Response:
        last_error: ProviderUnavailableError | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            request = build()
            try:
                response = await self.http.send(request, stream=stream)
            except httpx.TransportError as error:
                last_error = ProviderUnavailableError(
                    f"{self.config.role}: {type(error).__name__} while calling {request.url.path}"
                )
            else:
                if response.is_success:
                    return response
                await response.aread()
                await response.aclose()
                if _is_retryable(response.status_code):
                    last_error = ProviderUnavailableError(
                        f"{self.config.role}: HTTP {response.status_code} "
                        f"from {request.url.path}: {_error_message(response)}"
                    )
                else:
                    raise self._error_for(response)
            if attempt < self.retry.max_attempts:
                log.warning(
                    "model request retry role=%s attempt=%s/%s reason=%s",
                    self.config.role,
                    attempt,
                    self.retry.max_attempts,
                    last_error,
                )
                await self._sleep(self.retry.delay_for(attempt))
        assert last_error is not None
        raise last_error

    def _error_for(self, response: httpx.Response) -> ProviderError:
        status = response.status_code
        message = _error_message(response)
        role = self.config.role
        if status == 402:
            # Кончились деньги на аккаунте агрегатора: это инцидент, а не сбой
            # одного запроса — обработка всех интервью встанет до пополнения.
            log.error(
                "INCIDENT: model provider requires payment role=%s base_url=%s model=%s: %s",
                role,
                self.config.base_url,
                self.config.model,
                message,
            )
            return ProviderConfigurationError(f"{role}: payment required (HTTP 402): {message}")
        if status in (401, 403):
            return ProviderConfigurationError(f"{role}: authentication failed (HTTP {status})")
        if status == 404:
            return ProviderConfigurationError(
                f"{role}: model or endpoint not found (HTTP 404): {message}"
            )
        return ProviderResponseError(
            f"{role}: HTTP {status}: {message}", upstream_status=status, upstream_message=message
        )


async def iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Выдать поля ``data`` событий SSE (многострочные данные склеиваются).

    Событие с пустыми данными (``data:`` без значения — так некоторые прокси
    держат соединение) по спецификации SSE не доставляется, поэтому пропускается.
    """
    buffer: list[str] = []
    async for line in response.aiter_lines():
        line = line.rstrip("\r")
        if line == "":
            data = "\n".join(buffer)
            buffer = []
            if data.strip():
                yield data
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            buffer.append(value[1:] if value.startswith(" ") else value)
    data = "\n".join(buffer)
    if data.strip():
        yield data


def _parse_usage(payload: dict[str, Any] | None) -> Usage | None:
    if not payload:
        return None
    return Usage(
        prompt_tokens=int(payload.get("prompt_tokens") or 0),
        completion_tokens=int(payload.get("completion_tokens") or 0),
        total_tokens=int(payload.get("total_tokens") or 0),
    )


def parse_chat_response(payload: dict[str, Any], *, role: str) -> LLMResponse:
    choices = payload.get("choices") or []
    if not choices:
        raise ProviderResponseError(f"{role}: response has no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    tool_calls = [
        ToolCall(
            id=str(call.get("id") or f"call_{index}"),
            name=str((call.get("function") or {}).get("name") or ""),
            arguments=str((call.get("function") or {}).get("arguments") or ""),
        )
        for index, call in enumerate(message.get("tool_calls") or [])
    ]
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        raw=payload,
        usage=_parse_usage(payload.get("usage")),
        finish_reason=choice.get("finish_reason"),
    )


def parse_chat_chunk(payload: dict[str, Any]) -> LLMDelta | None:
    choices = payload.get("choices") or []
    usage = _parse_usage(payload.get("usage"))
    if not choices:
        return LLMDelta(usage=usage) if usage else None
    choice = choices[0]
    delta = choice.get("delta") or {}
    parts = [
        ToolCallDelta(
            index=int(call.get("index", position)),
            id=call.get("id"),
            name=(call.get("function") or {}).get("name"),
            arguments=str((call.get("function") or {}).get("arguments") or ""),
        )
        for position, call in enumerate(delta.get("tool_calls") or [])
    ]
    return LLMDelta(
        content=delta.get("content") or None,
        tool_calls_delta=parts or None,
        finish_reason=choice.get("finish_reason"),
        usage=usage,
    )


class OpenAICompatibleLLM(LLMProvider):
    def __init__(self, config: RoleConfig, *, client: OpenAICompatibleClient | None = None) -> None:
        self.config = config
        self.role = config.role
        self.model = config.model
        self.client = client or OpenAICompatibleClient(config)
        self._json_schema_unsupported = False

    def _body(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
        if response_format:
            body["response_format"] = self._effective_format(response_format)
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        return body

    def _effective_format(self, response_format: dict[str, Any]) -> dict[str, Any]:
        if response_format.get("type") == "json_schema":
            if self._json_schema_unsupported:
                return {"type": "json_object"}
            schema = dict(response_format.get("json_schema") or {})
            # strict=true требует, чтобы схема была без optional-полей и с
            # additionalProperties=false на каждом уровне — pydantic-схемы этому
            # не соответствуют; валидируем на своей стороне.
            schema.setdefault("strict", False)
            return {"type": "json_schema", "json_schema": schema}
        return response_format

    async def chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        body = self._body(
            messages,
            tools=tools,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            payload = await self.client.request_json("/chat/completions", json_body=body)
        except ProviderResponseError as error:
            wants_schema = body.get("response_format", {}).get("type") == "json_schema"
            if not (wants_schema and _rejects_format(error, "response_format", "json_schema")):
                raise
            # Агрегатор или модель не знают json_schema — просим просто JSON:
            # схема и так в промпте, а валидирует ответ pydantic.
            log.warning("role=%s: json_schema rejected, falling back to json_object", self.role)
            self._json_schema_unsupported = True
            body["response_format"] = {"type": "json_object"}
            payload = await self.client.request_json("/chat/completions", json_body=body)
        return parse_chat_response(payload, role=self.role)

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LLMDelta]:
        body = self._body(
            messages,
            tools=tools,
            response_format=None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        body["stream"] = True
        async with self.client.stream("/chat/completions", json_body=body) as response:
            async for data in iter_sse_data(response):
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError as error:
                    raise ProviderResponseError(
                        f"{self.role}: malformed stream chunk: {data[:120]!r}"
                    ) from error
                if not isinstance(chunk, dict):
                    raise ProviderResponseError(
                        f"{self.role}: unexpected stream chunk shape: {data[:120]!r}"
                    )
                # Ошибку посреди стрима агрегаторы шлют обычным событием при
                # статусе 200 (лимит, обрыв у модели); молча оборвать стрим
                # значило бы отдать пользователю усечённый ответ как полный.
                error_message = _chunk_error_message(chunk)
                if error_message is not None:
                    raise ProviderResponseError(
                        f"{self.role}: error in stream: {error_message}",
                        upstream_status=200,
                        upstream_message=error_message,
                    )
                delta = parse_chat_chunk(chunk)
                if delta is not None:
                    yield delta


def _extension_for(content_type: str) -> str:
    base = content_type.split(";", 1)[0].strip().lower()
    return _AUDIO_EXTENSIONS.get(base) or mimetypes.guess_extension(base) or ".bin"


def parse_transcript(payload: dict[str, Any], *, language: str | None) -> Transcript:
    text = str(payload.get("text") or "").strip()
    segments: list[TranscriptSegment] = []
    for item in payload.get("segments") or []:
        if not isinstance(item, dict):
            continue
        segment_text = str(item.get("text") or "").strip()
        if not segment_text:
            continue
        segments.append(
            TranscriptSegment(
                start_s=float(item.get("start") or 0.0),
                end_s=float(item.get("end") or 0.0),
                text=segment_text,
            )
        )
    if not segments and text:
        # Без таймкодов цитаты в отчёте всё равно должны на что-то ссылаться:
        # одна псевдо-сегмента на весь ответ.
        segments.append(
            TranscriptSegment(start_s=0.0, end_s=float(payload.get("duration") or 0.0), text=text)
        )
    return Transcript(
        text=text,
        segments=segments,
        language=payload.get("language") or language,
        raw=payload,
    )


class OpenAICompatibleSTT(STTProvider):
    def __init__(self, config: RoleConfig, *, client: OpenAICompatibleClient | None = None) -> None:
        self.config = config
        self.model = config.model
        self.client = client or OpenAICompatibleClient(config)
        self._verbose_json_unsupported = False

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str = "ru",
        prompt: str | None = None,
    ) -> Transcript:
        if len(audio) > MAX_AUDIO_BYTES:
            raise ProviderConfigurationError(
                f"stt: audio is {len(audio) / (1024 * 1024):.1f} MB, provider limit is "
                f"{MAX_AUDIO_BYTES // (1024 * 1024)} MB; extract a compressed audio track first"
            )
        if not audio:
            raise ProviderConfigurationError("stt: audio is empty")
        files = {"file": (f"audio{_extension_for(content_type)}", audio, content_type)}
        data: dict[str, Any] = {
            "model": self.model,
            "language": language,
            "response_format": "json" if self._verbose_json_unsupported else "verbose_json",
        }
        if prompt:
            data["prompt"] = prompt
        try:
            payload = await self.client.request_json(
                "/audio/transcriptions", data=data, files=files
            )
        except ProviderResponseError as error:
            wants_verbose = data["response_format"] == "verbose_json"
            if not (wants_verbose and _rejects_format(error, "response_format", "verbose_json")):
                raise
            # Не все модели умеют verbose_json (gpt-4o-transcribe отдаёт только
            # json); таймкоды тогда заменит псевдо-сегмента. Запоминаем, чтобы
            # не платить лишним запросом за каждый ответ кандидата.
            log.warning("stt: verbose_json rejected by provider, retrying with json")
            self._verbose_json_unsupported = True
            data["response_format"] = "json"
            payload = await self.client.request_json(
                "/audio/transcriptions", data=data, files=files
            )
        return parse_transcript(payload, language=language)


class OpenAICompatibleTTS(TTSProvider):
    def __init__(self, config: RoleConfig, *, client: OpenAICompatibleClient | None = None) -> None:
        self.config = config
        self.model = config.model
        self.client = client or OpenAICompatibleClient(config)

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        audio_format: str = "mp3",
    ) -> AudioResult:
        if not text.strip():
            raise ProviderConfigurationError("tts: text is empty")
        body = {
            "model": self.model,
            "input": text,
            "voice": voice or self.default_voice,
            "response_format": audio_format,
        }
        response = await self.client.request("/audio/speech", json_body=body)
        header = response.headers.get("content-type", "")
        content_type = AUDIO_CONTENT_TYPES.get(audio_format) or (
            header if header.startswith("audio/") else "application/octet-stream"
        )
        if not response.content:
            raise ProviderResponseError("tts: provider returned empty audio")
        return AudioResult(data=response.content, content_type=content_type)
