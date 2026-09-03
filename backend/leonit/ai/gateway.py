"""Фасад шлюза: провайдер на роль по текущим настройкам.

Экземпляры кэшируются по конфигурации, а не по имени роли: у провайдера есть
состояние (breaker, признак «json_schema не поддерживается»), которое должно
переживать запросы, но сбрасываться при смене настроек.
"""

from __future__ import annotations

from leonit.ai.config import LLM_ROLES, RoleConfig, get_role_config
from leonit.ai.http_client import close_http_clients, forget_http_clients
from leonit.ai.providers.base import LLMProvider, STTProvider, TTSProvider
from leonit.ai.providers.fake import FakeLLM, FakeSTT, FakeTTS
from leonit.ai.providers.openai_compatible import (
    OpenAICompatibleLLM,
    OpenAICompatibleSTT,
    OpenAICompatibleTTS,
)
from leonit.core.config import Settings

_llms: dict[RoleConfig, LLMProvider] = {}
_stts: dict[RoleConfig, STTProvider] = {}
_ttss: dict[RoleConfig, TTSProvider] = {}


def get_llm(role: str, *, settings: Settings | None = None) -> LLMProvider:
    if role not in LLM_ROLES:
        raise ValueError(f"{role!r} is not an LLM role; expected one of {LLM_ROLES}")
    config = get_role_config(role, settings)
    provider = _llms.get(config)
    if provider is None:
        provider = FakeLLM(config) if config.provider == "fake" else OpenAICompatibleLLM(config)
        _llms[config] = provider
    return provider


def get_stt(*, settings: Settings | None = None) -> STTProvider:
    config = get_role_config("stt", settings)
    provider = _stts.get(config)
    if provider is None:
        provider = FakeSTT(config) if config.provider == "fake" else OpenAICompatibleSTT(config)
        _stts[config] = provider
    return provider


def get_tts(*, settings: Settings | None = None) -> TTSProvider:
    config = get_role_config("tts", settings)
    provider = _ttss.get(config)
    if provider is None:
        provider = FakeTTS(config) if config.provider == "fake" else OpenAICompatibleTTS(config)
        _ttss[config] = provider
    return provider


def reset_gateway() -> None:
    """Забыть провайдеров и HTTP-клиентов (тесты, смена настроек)."""
    _llms.clear()
    _stts.clear()
    _ttss.clear()
    forget_http_clients()


async def shutdown_gateway() -> None:
    """Аккуратно закрыть пулы соединений при остановке процесса."""
    _llms.clear()
    _stts.clear()
    _ttss.clear()
    await close_http_clients()
