from __future__ import annotations

import httpx
import respx

from leonit.ai import http_client
from leonit.ai.diagnostics import check_models
from leonit.ai.gateway import cached_provider_count, get_llm
from leonit.core.config import Settings

ADHOC_BASE_URL = "https://adhoc.test/v1"


async def test_check_models_with_fake_provider() -> None:
    statuses = await check_models()
    assert [status.role for status in statuses] == [
        "evaluator",
        "assistant",
        "interviewer",
        "stt",
        "tts",
    ]
    for status in statuses:
        assert status.provider == "fake"
        assert status.configured and status.ok is True
        assert status.error is None
        assert isinstance(status.latency_ms, int)
    as_dict = statuses[0].as_dict()
    assert as_dict["model"] == "claude-sonnet-5" and as_dict["base_url"].startswith("https://")
    # Проверка с настройками процесса греет тот же кэш, что и рабочий код.
    assert cached_provider_count() == 5
    assert get_llm("evaluator") is get_llm("evaluator")


async def test_check_models_reports_unconfigured_roles_without_network() -> None:
    settings = Settings(_env_file=None, MODEL_PROVIDER="openai_compatible")
    statuses = await check_models(settings=settings)
    assert all(status.provider == "openai_compatible" for status in statuses)
    assert all(not status.configured and status.ok is None for status in statuses)
    assert all("API key is not set" in (status.error or "") for status in statuses)


async def test_check_models_with_adhoc_settings_leaves_nothing_cached() -> None:
    # Страница настроек проверяет ещё не сохранённые значения: провайдеры и пул
    # соединений под чужой base URL не должны оседать в памяти процесса.
    settings = Settings(
        _env_file=None,
        MODEL_PROVIDER="openai_compatible",
        MODEL_DEFAULT_API_KEY="adhoc-key",
        MODEL_DEFAULT_BASE_URL=ADHOC_BASE_URL,
    )
    chat_payload = {"choices": [{"message": {"content": "ок"}, "finish_reason": "stop"}]}
    with respx.mock(base_url=ADHOC_BASE_URL) as mock:
        chat = mock.post("/chat/completions").mock(
            return_value=httpx.Response(200, json=chat_payload)
        )
        mock.post("/audio/transcriptions").mock(
            return_value=httpx.Response(200, json={"text": "тишина"})
        )
        mock.post("/audio/speech").mock(
            return_value=httpx.Response(
                200, content=b"ID3\x03", headers={"content-type": "audio/mpeg"}
            )
        )
        statuses = await check_models(settings=settings)
    assert [status.ok for status in statuses] == [True] * 5, [s.error for s in statuses]
    assert chat.calls.last.request.headers["authorization"] == "Bearer adhoc-key"
    assert cached_provider_count() == 0
    assert (ADHOC_BASE_URL, None) not in http_client._clients
