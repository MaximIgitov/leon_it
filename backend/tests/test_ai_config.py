from __future__ import annotations

import pytest

from leonit.ai.config import all_role_configs, get_role_config
from leonit.core.config import Settings


def _settings(**overrides) -> Settings:
    # conftest выставляет MODEL_PROVIDER=fake в окружении; здесь проверяем автовыбор.
    overrides.setdefault("MODEL_PROVIDER", None)
    return Settings(_env_file=None, **overrides)


def test_provider_is_fake_without_any_api_key() -> None:
    assert _settings().effective_model_provider == "fake"


def test_provider_is_openai_compatible_when_any_role_has_key() -> None:
    assert _settings(MODEL_STT_API_KEY="k").effective_model_provider == "openai_compatible"
    assert _settings(MODEL_DEFAULT_API_KEY="k").effective_model_provider == "openai_compatible"


def test_explicit_provider_wins_over_autodetection() -> None:
    settings = _settings(MODEL_DEFAULT_API_KEY="k", MODEL_PROVIDER="fake")
    assert settings.effective_model_provider == "fake"


def test_production_rejects_fake_provider_unless_allowed() -> None:
    with pytest.raises(ValueError, match="MODEL_PROVIDER=fake"):
        _settings(ENVIRONMENT="production", JWT_SECRET="x" * 40, CORS_ORIGINS=["https://a.b"])
    settings = _settings(
        ENVIRONMENT="production",
        JWT_SECRET="x" * 40,
        CORS_ORIGINS=["https://a.b"],
        MODEL_ALLOW_FAKE_IN_PRODUCTION=True,
    )
    assert settings.effective_model_provider == "fake"


def test_role_config_falls_back_to_defaults() -> None:
    settings = _settings(
        MODEL_DEFAULT_API_KEY="default-key",
        MODEL_DEFAULT_PROXY_URL="http://proxy:3128",
        MODEL_STT_BASE_URL="https://audio.example/v1/",
        MODEL_STT_API_KEY="stt-key",
        MODEL_STT_TIMEOUT_S=7,
    )
    evaluator = get_role_config("evaluator", settings)
    assert evaluator.base_url == "https://api.aitunnel.ru/v1"
    assert evaluator.api_key == "default-key"
    assert evaluator.proxy_url == "http://proxy:3128"
    assert evaluator.model == "claude-sonnet-5"
    assert evaluator.provider == "openai_compatible"
    assert evaluator.configured

    stt = get_role_config("stt", settings)
    assert stt.base_url == "https://audio.example/v1"
    assert stt.api_key == "stt-key"
    assert stt.timeout_s == 7
    assert stt.model == "gpt-4o-transcribe"


def test_default_models_per_role() -> None:
    models = {config.role: config.model for config in all_role_configs(_settings())}
    assert models == {
        "evaluator": "claude-sonnet-5",
        "assistant": "claude-sonnet-5",
        "interviewer": "claude-haiku-4.5",
        "stt": "gpt-4o-transcribe",
        "tts": "gpt-4o-mini-tts",
    }


def test_unconfigured_real_role_is_reported() -> None:
    settings = _settings(MODEL_PROVIDER="openai_compatible")
    config = get_role_config("tts", settings)
    assert not config.configured
    assert config.redacted()["api_key"] is None


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown model role"):
        get_role_config("oracle", _settings())
