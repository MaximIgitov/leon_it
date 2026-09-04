from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from leonit.ai.circuit_breaker import CircuitBreaker
from leonit.ai.config import RoleConfig
from leonit.ai.providers.base import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderUnavailableError,
    StreamAccumulator,
)
from leonit.ai.providers.openai_compatible import (
    MAX_AUDIO_BYTES,
    OpenAICompatibleClient,
    OpenAICompatibleLLM,
    OpenAICompatibleSTT,
    OpenAICompatibleTTS,
    RetryPolicy,
)

BASE_URL = "https://models.test/v1"


def _config(role: str = "evaluator", *, api_key: str | None = "secret") -> RoleConfig:
    return RoleConfig(
        role=role,
        provider="openai_compatible",
        base_url=BASE_URL,
        api_key=api_key,
        model=f"model-{role}",
        proxy_url=None,
        timeout_s=5.0,
    )


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


def _client(
    http: httpx.AsyncClient, role: str = "evaluator", *, api_key: str | None = "secret", **kw
) -> OpenAICompatibleClient:
    kw.setdefault("retry", RetryPolicy(max_attempts=3, backoff_base_s=0))
    kw.setdefault("breaker", CircuitBreaker(failure_threshold=2, recovery_timeout_s=60))
    return OpenAICompatibleClient(_config(role, api_key=api_key), http=http, **kw)


def _chat_payload(content: str = "Привет", **extra) -> dict:
    return {
        "id": "chatcmpl-1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, **extra},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


async def test_chat_success_sends_auth_model_and_parses_usage(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=_chat_payload())
        )
        response = await llm.chat(
            [{"role": "user", "content": "hi"}], temperature=0.2, max_tokens=50
        )
    assert response.content == "Привет"
    assert response.usage is not None and response.usage.total_tokens == 15
    assert response.finish_reason == "stop"
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body["model"] == "model-evaluator"
    assert body["temperature"] == 0.2 and body["max_tokens"] == 50


async def test_chat_parses_tool_calls(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    payload = _chat_payload(
        None,
        tool_calls=[
            {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": '{"a": 1}'}}
        ],
    )
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(return_value=httpx.Response(200, json=payload))
        response = await llm.chat([{"role": "user", "content": "go"}], tools=[{"type": "function"}])
    assert response.tool_calls[0].name == "f"
    assert response.tool_calls[0].arguments_json() == {"a": 1}


async def test_retries_on_503_then_succeeds(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            side_effect=[
                httpx.Response(503, text="down"),
                httpx.Response(200, json=_chat_payload("ok")),
            ]
        )
        response = await llm.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert route.call_count == 2


async def test_retries_on_network_error(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=_chat_payload("ok"))]
        )
        response = await llm.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert route.call_count == 2


async def test_gives_up_after_max_attempts(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": {"message": "slow down"}})
        )
        with pytest.raises(ProviderUnavailableError, match="HTTP 429"):
            await llm.chat([{"role": "user", "content": "hi"}])
    assert route.call_count == 3


async def test_402_is_configuration_error_without_retry(http: httpx.AsyncClient, caplog) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            return_value=httpx.Response(402, json={"error": {"message": "insufficient balance"}})
        )
        with (
            caplog.at_level("ERROR"),
            pytest.raises(ProviderConfigurationError, match="payment required"),
        ):
            await llm.chat([{"role": "user", "content": "hi"}])
    assert route.call_count == 1
    assert any("INCIDENT" in record.message for record in caplog.records)


async def test_401_is_configuration_error(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(return_value=httpx.Response(401, json={}))
        with pytest.raises(ProviderConfigurationError, match="authentication"):
            await llm.chat([{"role": "user", "content": "hi"}])


async def test_missing_api_key_fails_before_any_request(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(api_key=None), client=_client(http, api_key=None))
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        route = mock.post("/chat/completions")
        with pytest.raises(ProviderConfigurationError, match="MODEL_EVALUATOR_API_KEY"):
            await llm.chat([{"role": "user", "content": "hi"}])
    assert route.call_count == 0


async def test_circuit_breaker_opens_and_fails_fast(http: httpx.AsyncClient) -> None:
    client = _client(http, breaker=CircuitBreaker(failure_threshold=2, recovery_timeout_s=60))
    llm = OpenAICompatibleLLM(_config(), client=client)
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(return_value=httpx.Response(500, text="boom"))
        for _ in range(2):
            with pytest.raises(ProviderUnavailableError, match="HTTP 500"):
                await llm.chat([{"role": "user", "content": "hi"}])
        assert route.call_count == 6  # два вызова × три попытки
        assert client.breaker.state == "open"
        with pytest.raises(ProviderUnavailableError, match="circuit breaker is open"):
            await llm.chat([{"role": "user", "content": "hi"}])
        assert route.call_count == 6  # запрос в сеть не ушёл


def test_circuit_breaker_half_open_recovers_and_retrips() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=10, clock=lambda: now[0])
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open" and not breaker.allow()
    now[0] = 10.0
    assert breaker.state == "half_open"
    assert breaker.allow() and not breaker.allow()  # один пробный запрос
    breaker.record_failure()
    assert breaker.state == "open"
    now[0] = 20.0
    assert breaker.allow()
    breaker.record_success()
    assert breaker.state == "closed" and breaker.failures == 0


def test_circuit_breaker_release_probe_frees_half_open_slot() -> None:
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=10, clock=lambda: now[0])
    breaker.record_failure()
    now[0] = 10.0
    assert breaker.allow() and not breaker.allow()
    breaker.release_probe()
    assert breaker.state == "half_open" and breaker.allow()
    # В закрытом состоянии возврат слота ничего не ломает.
    breaker.record_success()
    breaker.release_probe()
    assert breaker.state == "closed" and breaker.allow()


def _tripped_client(http: httpx.AsyncClient, now: list[float]) -> OpenAICompatibleClient:
    """Клиент с breaker, который открывается после одного сбоя и ждёт 10 «секунд»."""
    return _client(
        http,
        retry=RetryPolicy(max_attempts=1, backoff_base_s=0),
        breaker=CircuitBreaker(failure_threshold=1, recovery_timeout_s=10, clock=lambda: now[0]),
    )


_SCHEMA_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "X", "schema": {"type": "object"}},
}


async def test_half_open_probe_rejected_with_400_closes_breaker(http: httpx.AsyncClient) -> None:
    now = [0.0]
    client = _tripped_client(http, now)
    llm = OpenAICompatibleLLM(_config(), client=client)
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            side_effect=[
                httpx.Response(503, text="down"),
                httpx.Response(400, json={"error": {"message": "json_schema is not supported"}}),
                httpx.Response(200, json=_chat_payload('{"a": 1}')),
            ]
        )
        with pytest.raises(ProviderUnavailableError, match="HTTP 503"):
            await llm.chat([{"role": "user", "content": "hi"}])
        assert client.breaker.state == "open"
        now[0] = 10.0
        assert client.breaker.state == "half_open"
        # Пробный запрос получил 400: провайдер жив, контур закрыт, и фолбэк на
        # json_object проходит вторым запросом, а не упирается в «breaker is open».
        response = await llm.chat(
            [{"role": "user", "content": "hi"}], response_format=_SCHEMA_FORMAT
        )
    assert response.content == '{"a": 1}'
    assert route.call_count == 3
    assert client.breaker.state == "closed" and client.breaker.allow()


async def test_half_open_probe_with_401_does_not_jam_breaker(http: httpx.AsyncClient) -> None:
    now = [0.0]
    client = _tripped_client(http, now)
    llm = OpenAICompatibleLLM(_config(), client=client)
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(
            side_effect=[httpx.Response(503, text="down"), httpx.Response(401, json={})]
        )
        with pytest.raises(ProviderUnavailableError):
            await llm.chat([{"role": "user", "content": "hi"}])
        now[0] = 10.0
        with pytest.raises(ProviderConfigurationError, match="authentication"):
            await llm.chat([{"role": "user", "content": "hi"}])
    assert client.breaker.state == "closed" and client.breaker.allow()


async def test_cancelled_probe_returns_half_open_slot(http: httpx.AsyncClient) -> None:
    now = [0.0]
    client = _tripped_client(http, now)
    llm = OpenAICompatibleLLM(_config(), client=client)

    # Считаем попытки сами: respx не записывает вызов, если side effect бросил
    # BaseException (CancelledError — не Exception).
    attempts = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="down")
        if attempts == 2:
            raise asyncio.CancelledError
        return httpx.Response(200, json=_chat_payload("ok"))

    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(side_effect=respond)
        with pytest.raises(ProviderUnavailableError):
            await llm.chat([{"role": "user", "content": "hi"}])
        now[0] = 10.0
        with pytest.raises(asyncio.CancelledError):
            await llm.chat([{"role": "user", "content": "hi"}])
        # Исход пробы неизвестен: слот возвращён, следующий запрос снова пробный.
        assert client.breaker.state == "half_open"
        response = await llm.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert attempts == 3
    assert client.breaker.state == "closed"


async def test_missing_api_key_does_not_touch_breaker(http: httpx.AsyncClient) -> None:
    now = [0.0]
    client = _client(
        http,
        api_key=None,
        breaker=CircuitBreaker(failure_threshold=1, recovery_timeout_s=10, clock=lambda: now[0]),
    )
    client.breaker.record_failure()
    now[0] = 10.0
    llm = OpenAICompatibleLLM(_config(api_key=None), client=client)
    with (
        respx.mock(base_url=BASE_URL, assert_all_called=False),
        pytest.raises(ProviderConfigurationError, match="API key"),
    ):
        await llm.chat([{"role": "user", "content": "hi"}])
    assert client.breaker.state == "half_open" and client.breaker.allow()


async def test_json_schema_falls_back_to_json_object_on_400(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    schema_format = {
        "type": "json_schema",
        "json_schema": {"name": "X", "schema": {"type": "object"}},
    }
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            side_effect=[
                httpx.Response(400, json={"error": {"message": "response_format not supported"}}),
                httpx.Response(200, json=_chat_payload('{"a": 1}')),
                httpx.Response(200, json=_chat_payload('{"a": 2}')),
            ]
        )
        first = await llm.chat([{"role": "user", "content": "hi"}], response_format=schema_format)
        second = await llm.chat([{"role": "user", "content": "hi"}], response_format=schema_format)
    assert first.content == '{"a": 1}' and second.content == '{"a": 2}'
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert bodies[0]["response_format"]["type"] == "json_schema"
    assert bodies[0]["response_format"]["json_schema"]["strict"] is False
    assert bodies[1]["response_format"] == {"type": "json_object"}
    # Провайдер запомнил, что json_schema не поддерживается: третий запрос сразу json_object.
    assert bodies[2]["response_format"] == {"type": "json_object"}
    assert route.call_count == 3


async def test_other_400_is_response_error(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(
            return_value=httpx.Response(400, json={"error": {"message": "bad"}})
        )
        with pytest.raises(ProviderResponseError, match="HTTP 400: bad") as info:
            await llm.chat([{"role": "user", "content": "hi"}])
    assert info.value.upstream_status == 400
    assert info.value.upstream_message == "bad"


async def test_json_schema_fallback_requires_format_rejection(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            side_effect=[
                httpx.Response(400, json={"error": {"message": "messages[0].role: invalid"}}),
                httpx.Response(200, json=_chat_payload('{"a": 1}')),
            ]
        )
        # 400 не про формат ответа: исходная ошибка наружу, второго запроса нет.
        with pytest.raises(ProviderResponseError, match="invalid") as info:
            await llm.chat([{"role": "user", "content": "hi"}], response_format=_SCHEMA_FORMAT)
        assert info.value.upstream_status == 400
        assert route.call_count == 1
        # И признак «json_schema не поддерживается» не выставлен.
        await llm.chat([{"role": "user", "content": "hi"}], response_format=_SCHEMA_FORMAT)
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert [body["response_format"]["type"] for body in bodies] == ["json_schema", "json_schema"]


def _sse(*events: dict | str) -> bytes:
    lines = []
    for event in events:
        data = event if isinstance(event, str) else json.dumps(event)
        lines.append(f"data: {data}\n\n")
    return "".join(lines).encode()


def _chunk(delta: dict, finish_reason: str | None = None) -> dict:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}


async def test_stream_chat_parses_sse_with_tool_calls(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    body = _sse(
        _chunk({"role": "assistant", "content": ""}),
        _chunk({"content": "Сей"}),
        _chunk({"content": "час"}),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "rank", "arguments": ""},
                    }
                ]
            }
        ),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"vacancy'}}]}),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 1,
                        "id": "call_b",
                        "type": "function",
                        "function": {"name": "summary", "arguments": "{}"},
                    }
                ]
            }
        ),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '_id": 7}'}}]}),
        _chunk({}, "tool_calls"),
        "[DONE]",
    )
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            return_value=httpx.Response(
                200, content=body, headers={"content-type": "text/event-stream"}
            )
        )
        accumulator = StreamAccumulator()
        async for delta in llm.stream_chat(
            [{"role": "user", "content": "hi"}], tools=[{"type": "function"}]
        ):
            accumulator.add(delta)
    assert json.loads(route.calls.last.request.content)["stream"] is True
    response = accumulator.response()
    assert response.content == "Сейчас"
    assert response.finish_reason == "tool_calls"
    assert [(call.id, call.name) for call in response.tool_calls] == [
        ("call_a", "rank"),
        ("call_b", "summary"),
    ]
    assert response.tool_calls[0].arguments_json() == {"vacancy_id": 7}


async def test_stream_chat_retries_failed_status_before_streaming(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/chat/completions").mock(
            side_effect=[
                httpx.Response(502, text="bad gateway"),
                httpx.Response(200, content=_sse(_chunk({"content": "ok"}, "stop"), "[DONE]")),
            ]
        )
        deltas = [delta async for delta in llm.stream_chat([{"role": "user", "content": "hi"}])]
    assert route.call_count == 2
    assert [delta.content for delta in deltas] == ["ok"]


class _BrokenStream(httpx.AsyncByteStream):
    """Тело, которое обрывается после первых чанков: провайдер умер посреди стрима."""

    def __init__(self, chunks: list[bytes], error: Exception) -> None:
        self._chunks = chunks
        self._error = error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk
        raise self._error


def _sse_response(body: bytes | httpx.AsyncByteStream) -> httpx.Response:
    headers = {"content-type": "text/event-stream"}
    if isinstance(body, bytes):
        return httpx.Response(200, content=body, headers=headers)
    return httpx.Response(200, stream=body, headers=headers)


async def test_stream_skips_empty_data_and_comments(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    # Прокси держат соединение комментариями и пустыми data: это не чанки.
    body = b": keep-alive\n\ndata:\n\ndata: \n\n" + _sse(
        _chunk({"content": "ok"}, "stop"), "[DONE]"
    )
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(return_value=_sse_response(body))
        deltas = [delta async for delta in llm.stream_chat([{"role": "user", "content": "hi"}])]
    assert [delta.content for delta in deltas] == ["ok"]
    assert deltas[0].finish_reason == "stop"


async def test_stream_error_event_raises_response_error(http: httpx.AsyncClient) -> None:
    llm = OpenAICompatibleLLM(_config(), client=_client(http))
    body = _sse(
        _chunk({"content": "част"}),
        {"error": {"message": "quota exceeded", "type": "insufficient_quota", "code": 429}},
    )
    collected: list[str | None] = []
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(return_value=_sse_response(body))
        with pytest.raises(ProviderResponseError, match="quota exceeded") as info:
            async for delta in llm.stream_chat([{"role": "user", "content": "hi"}]):
                collected.append(delta.content)
    assert collected == ["част"]
    assert info.value.upstream_message == "quota exceeded"


async def test_stream_transport_error_is_unavailable_and_trips_breaker(
    http: httpx.AsyncClient,
) -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=60)
    llm = OpenAICompatibleLLM(_config(), client=_client(http, breaker=breaker))
    stream = _BrokenStream([_sse(_chunk({"content": "нач"}))], httpx.ReadError("connection reset"))
    collected: list[str | None] = []
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/chat/completions").mock(return_value=_sse_response(stream))
        with pytest.raises(ProviderUnavailableError, match="ReadError"):
            async for delta in llm.stream_chat([{"role": "user", "content": "hi"}]):
                collected.append(delta.content)
    assert collected == ["нач"]
    # Обрыв тела — такой же отказ провайдера, как обрыв до ответа.
    assert breaker.failures == 1 and breaker.state == "open"


async def test_stt_verbose_json_returns_segments(http: httpx.AsyncClient) -> None:
    stt = OpenAICompatibleSTT(_config("stt"), client=_client(http, "stt"))
    payload = {
        "text": "Я работал с FastAPI. Потом с Django.",
        "language": "russian",
        "duration": 4.2,
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.0, "text": " Я работал с FastAPI."},
            {"id": 1, "start": 2.0, "end": 4.2, "text": " Потом с Django."},
        ],
    }
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/audio/transcriptions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        transcript = await stt.transcribe(
            b"RIFF....", content_type="audio/wav", prompt="FastAPI, Django"
        )
    assert transcript.text == "Я работал с FastAPI. Потом с Django."
    assert [(s.start_s, s.end_s, s.text) for s in transcript.segments] == [
        (0.0, 2.0, "Я работал с FastAPI."),
        (2.0, 4.2, "Потом с Django."),
    ]
    assert transcript.language == "russian"
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="response_format"\r\n\r\nverbose_json' in request.content
    assert b'name="prompt"\r\n\r\nFastAPI, Django' in request.content
    assert b'filename="audio.wav"' in request.content
    assert b'name="model"\r\n\r\nmodel-stt' in request.content


async def test_stt_without_segments_builds_pseudo_segment(http: httpx.AsyncClient) -> None:
    stt = OpenAICompatibleSTT(_config("stt"), client=_client(http, "stt"))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/audio/transcriptions").mock(
            side_effect=[
                httpx.Response(400, json={"error": {"message": "verbose_json unsupported"}}),
                httpx.Response(200, json={"text": "Только текст"}),
            ]
        )
        transcript = await stt.transcribe(b"\x00\x01", content_type="audio/webm")
    assert route.call_count == 2
    assert b'name="response_format"\r\n\r\njson' in route.calls.last.request.content
    assert transcript.text == "Только текст"
    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "Только текст"
    assert transcript.language == "ru"


async def test_stt_remembers_verbose_json_unsupported(http: httpx.AsyncClient) -> None:
    stt = OpenAICompatibleSTT(_config("stt"), client=_client(http, "stt"))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/audio/transcriptions").mock(
            side_effect=[
                httpx.Response(400, json={"error": {"message": "response_format verbose_json"}}),
                httpx.Response(200, json={"text": "раз"}),
                httpx.Response(200, json={"text": "два"}),
            ]
        )
        await stt.transcribe(b"\x00\x01", content_type="audio/webm")
        second = await stt.transcribe(b"\x00\x01", content_type="audio/webm")
    assert second.text == "два"
    # Второй ответ кандидата не платит лишним запросом: сразу json.
    assert route.call_count == 3
    assert b'name="response_format"\r\n\r\njson' in route.calls.last.request.content


async def test_stt_json_fallback_requires_format_rejection(http: httpx.AsyncClient) -> None:
    stt = OpenAICompatibleSTT(_config("stt"), client=_client(http, "stt"))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/audio/transcriptions").mock(
            side_effect=[
                httpx.Response(400, json={"error": {"message": "Invalid file format"}}),
                httpx.Response(200, json={"text": "не должно дойти"}),
            ]
        )
        with pytest.raises(ProviderResponseError, match="Invalid file format"):
            await stt.transcribe(b"\x00\x01", content_type="audio/webm")
        assert route.call_count == 1
        # Ложный вывод «verbose_json не поддерживается» не запомнен.
        await stt.transcribe(b"\x00\x01", content_type="audio/webm")
    assert b'name="response_format"\r\n\r\nverbose_json' in route.calls.last.request.content


async def test_stt_rejects_files_over_limit(http: httpx.AsyncClient) -> None:
    stt = OpenAICompatibleSTT(_config("stt"), client=_client(http, "stt"))
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        route = mock.post("/audio/transcriptions")
        with pytest.raises(ProviderConfigurationError, match="25 MB"):
            await stt.transcribe(b"\x00" * (MAX_AUDIO_BYTES + 1), content_type="audio/wav")
    assert route.call_count == 0


async def test_tts_returns_bytes_with_content_type(http: httpx.AsyncClient) -> None:
    tts = OpenAICompatibleTTS(_config("tts"), client=_client(http, "tts"))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.post("/audio/speech").mock(
            return_value=httpx.Response(
                200, content=b"ID3\x03mp3bytes", headers={"content-type": "audio/mpeg"}
            )
        )
        result = await tts.synthesize("Расскажите о себе", audio_format="mp3")
    assert result.data == b"ID3\x03mp3bytes"
    assert result.content_type == "audio/mpeg"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "model": "model-tts",
        "input": "Расскажите о себе",
        "voice": "nova",
        "response_format": "mp3",
    }
