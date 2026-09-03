"""Проверка моделей: страница «настройки моделей» и smoke-тест стенда.

На каждую роль уходит крошечный реальный запрос — только так видно, что ключ
действует, модель существует у агрегатора и баланс не исчерпан. Роли
проверяются параллельно и независимо: одна неработающая не прячет остальные.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from time import perf_counter

from leonit.ai.config import LLM_ROLES, RoleConfig, all_role_configs
from leonit.ai.gateway import get_llm, get_stt, get_tts
from leonit.ai.providers.fake import silence_wav
from leonit.core.config import Settings

_PROBE_TIMEOUT_S = 30.0


@dataclass(slots=True)
class RoleStatus:
    role: str
    provider: str
    model: str
    base_url: str
    configured: bool
    ok: bool | None
    latency_ms: int | None
    error: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


async def _probe(config: RoleConfig, settings: Settings | None) -> None:
    if config.role in LLM_ROLES:
        await get_llm(config.role, settings=settings).chat(
            [{"role": "user", "content": "Ответь одним словом: ок"}], max_tokens=5
        )
    elif config.role == "stt":
        await get_stt(settings=settings).transcribe(
            silence_wav(0.5), content_type="audio/wav", language="ru"
        )
    elif config.role == "tts":
        await get_tts(settings=settings).synthesize("Проверка связи.")
    else:  # pragma: no cover - новые роли должны получить свою проверку
        raise ValueError(f"no probe for role {config.role!r}")


async def check_role(config: RoleConfig, *, settings: Settings | None = None) -> RoleStatus:
    status = RoleStatus(
        role=config.role,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        configured=config.configured,
        ok=None,
        latency_ms=None,
        error=None,
    )
    if not config.configured:
        status.error = f"API key is not set (MODEL_{config.role.upper()}_API_KEY)"
        return status
    started = perf_counter()
    try:
        await asyncio.wait_for(_probe(config, settings), timeout=_PROBE_TIMEOUT_S)
    except TimeoutError:
        status.ok = False
        status.error = f"no response within {_PROBE_TIMEOUT_S:.0f}s"
    except Exception as error:  # любая ошибка провайдера — это результат проверки
        status.ok = False
        status.error = f"{type(error).__name__}: {error}"
    else:
        status.ok = True
    status.latency_ms = int((perf_counter() - started) * 1000)
    return status


async def check_models(*, settings: Settings | None = None) -> list[RoleStatus]:
    configs = all_role_configs(settings)
    return list(await asyncio.gather(*(check_role(c, settings=settings) for c in configs)))
