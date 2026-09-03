from __future__ import annotations

from leonit.ai.diagnostics import check_models
from leonit.core.config import Settings


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


async def test_check_models_reports_unconfigured_roles_without_network() -> None:
    settings = Settings(_env_file=None, MODEL_PROVIDER="openai_compatible")
    statuses = await check_models(settings=settings)
    assert all(status.provider == "openai_compatible" for status in statuses)
    assert all(not status.configured and status.ok is None for status in statuses)
    assert all("API key is not set" in (status.error or "") for status in statuses)
