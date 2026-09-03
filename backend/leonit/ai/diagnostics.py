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
from leonit.ai.gateway import build_llm, build_stt, build_tts, get_llm, get_stt, get_tts
from leonit.ai.http_client import new_http_client
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
    # Проверка с переданными настройками (форма «настройки моделей» до их
    # сохранения) не должна оседать в кэше шлюза: провайдер и его пул
    # соединений живут ровно до конца проверки.
    adhoc = settings is not None
    http = None
    if adhoc and config.provider != "fake":
        http = new_http_client(config.base_url, config.proxy_url)
    try:
        if config.role in LLM_ROLES:
            llm = build_llm(config, http=http) if adhoc else get_llm(config.role)
            await llm.chat([{"role": "user", "content": "Ответь одним словом: ок"}], max_tokens=5)
        elif config.role == "stt":
            stt = build_stt(config, http=http) if adhoc else get_stt()
            await stt.transcribe(silence_wav(0.5), content_type="audio/wav", language="ru")
        elif config.role == "tts":
            tts = build_tts(config, http=http) if adhoc else get_tts()
            await tts.synthesize("Проверка связи.")
        else:  # pragma: no cover - новые роли должны получить свою проверку
            raise ValueError(f"no probe for role {config.role!r}")
    finally:
        if http is not None:
            await http.aclose()


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


def _print_report(statuses: list[RoleStatus]) -> None:
    for status in statuses:
        state = "не настроен" if not status.configured else ("ok" if status.ok else "ОШИБКА")
        latency = f" {status.latency_ms} мс" if status.latency_ms is not None else ""
        error = f" — {status.error}" if status.error else ""
        print(f"{status.role:<12} {status.provider:<18} {status.model:<32} {state}{latency}{error}")


def main() -> int:
    """``python -m leonit.ai.diagnostics`` — проверить модели по ролям (для runbook)."""
    import sys

    from leonit.core.config import get_settings

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    statuses = asyncio.run(check_models(settings=get_settings()))
    _print_report(statuses)
    return 0 if all(item.ok or not item.configured for item in statuses) else 1


if __name__ == "__main__":  # pragma: no cover - утилита командной строки
    raise SystemExit(main())
