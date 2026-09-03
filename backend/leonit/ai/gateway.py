"""Фасад шлюза: провайдер на роль по текущим настройкам.

Экземпляры кэшируются по конфигурации, а не по имени роли: у провайдера есть
состояние (breaker, признак «json_schema не поддерживается»), которое должно
переживать запросы, но сбрасываться при смене настроек. Кэш — только для
настроек процесса: разовые проверки с чужими настройками (``build_*``) в него
не попадают, иначе каждый введённый на странице настроек URL оставался бы в
памяти до перезапуска.
"""

from __future__ import annotations

import httpx

from leonit.ai.config import LLM_ROLES, RoleConfig, get_role_config
from leonit.ai.http_client import close_http_clients, forget_http_clients
from leonit.ai.providers.base import LLMProvider, STTProvider, TTSProvider
from leonit.ai.providers.fake import FakeLLM, FakeSTT, FakeTTS
from leonit.ai.providers.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleLLM,
    OpenAICompatibleSTT,
    OpenAICompatibleTTS,
)
from leonit.core.config import Settings

_llms: dict[RoleConfig, LLMProvider] = {}
_stts: dict[RoleConfig, STTProvider] = {}
_ttss: dict[RoleConfig, TTSProvider] = {}


def build_llm(config: RoleConfig, *, http: httpx.AsyncClient | None = None) -> LLMProvider:
    """Создать провайдера без кэширования; ``http`` — свой клиент вместо общего пула."""
    if config.role not in LLM_ROLES:
        raise ValueError(f"{config.role!r} is not an LLM role; expected one of {LLM_ROLES}")
    if config.provider == "fake":
        return FakeLLM(config)
    return OpenAICompatibleLLM(config, client=OpenAICompatibleClient(config, http=http))


def build_stt(config: RoleConfig, *, http: httpx.AsyncClient | None = None) -> STTProvider:
    if config.provider == "fake":
        return FakeSTT(config)
    return OpenAICompatibleSTT(config, client=OpenAICompatibleClient(config, http=http))


def build_tts(config: RoleConfig, *, http: httpx.AsyncClient | None = None) -> TTSProvider:
    if config.provider == "fake":
        return FakeTTS(config)
    return OpenAICompatibleTTS(config, client=OpenAICompatibleClient(config, http=http))


def get_llm(role: str, *, settings: Settings | None = None) -> LLMProvider:
    if role not in LLM_ROLES:
        raise ValueError(f"{role!r} is not an LLM role; expected one of {LLM_ROLES}")
    config = get_role_config(role, settings)
    provider = _llms.get(config)
    if provider is None:
        provider = _llms[config] = build_llm(config)
    return provider


def get_stt(*, settings: Settings | None = None) -> STTProvider:
    config = get_role_config("stt", settings)
    provider = _stts.get(config)
    if provider is None:
        provider = _stts[config] = build_stt(config)
    return provider


def get_tts(*, settings: Settings | None = None) -> TTSProvider:
    config = get_role_config("tts", settings)
    provider = _ttss.get(config)
    if provider is None:
        provider = _ttss[config] = build_tts(config)
    return provider


def cached_provider_count() -> int:
    """Сколько провайдеров держит кэш (диагностика и тесты на утечку)."""
    return len(_llms) + len(_stts) + len(_ttss)


def reset_gateway() -> None:
    """Забыть провайдеров и HTTP-клиентов, не закрывая соединения.

    Только для тестов: между ними меняется event loop, и закрыть старые пулы
    уже негде — их просто отпускают. В рантайме (lifespan приложения, остановка
    воркера) вызывайте ``shutdown_gateway``: он закрывает пулы соединений.
    """
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
