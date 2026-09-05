"""Конфигурация модели на роль.

Роли разведены намеренно: оценщик (``evaluator``) должен быть самым сильным и
может жить у одного агрегатора, речь (``stt``/``tts``) — у другого, который
умеет ``/audio/*``, а интервьюер — на дешёвой быстрой модели. Поэтому у каждой
роли свой ``base_url``/ключ/прокси, а общие ``MODEL_DEFAULT_*`` лишь фолбэк.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from leonit.core.config import MODEL_ROLES, ModelProvider, Settings, get_settings

ModelRole = Literal["evaluator", "assistant", "interviewer", "stt", "tts"]
LLM_ROLES: tuple[ModelRole, ...] = ("evaluator", "assistant", "interviewer")

# Оценщик пишет длинное структурированное заключение, ему нужен запас по
# времени; интервьюер отвечает в живом диалоге и ждать долго не должен.
_DEFAULT_TIMEOUTS_S: dict[str, float] = {
    "evaluator": 180.0,
    "assistant": 120.0,
    "interviewer": 60.0,
    "stt": 120.0,
    "tts": 60.0,
}

# Лимит генерации по ролям. Заключение оценщика на 3–5 вопросов — 2–4 тысячи
# токенов, ответ ассистента и план уточняющих вопросов — меньше. Без лимита
# агрегатор оценивает стоимость запроса по максимуму модели и при низком
# балансе отвечает 402 ещё до генерации, хотя списывает только за факт.
_DEFAULT_MAX_TOKENS: dict[str, int] = {
    "evaluator": 8192,
    "assistant": 4096,
    "interviewer": 1024,
}


@dataclass(frozen=True, slots=True)
class RoleConfig:
    role: str
    provider: ModelProvider
    base_url: str
    api_key: str | None
    model: str
    proxy_url: str | None
    timeout_s: float
    # Лимит генерации для LLM-ролей; None — не передавать (речь).
    max_tokens: int | None = None

    @property
    def configured(self) -> bool:
        """Можно ли делать запросы: фейку ключ не нужен, реальному — обязателен."""
        return self.provider == "fake" or bool(self.api_key)

    def redacted(self) -> dict[str, object]:
        """Для логов и страницы диагностики: без ключа."""
        data = asdict(self)
        data["api_key"] = "***" if self.api_key else None
        return data


def get_role_config(role: str, settings: Settings | None = None) -> RoleConfig:
    if role not in MODEL_ROLES:
        raise ValueError(f"unknown model role {role!r}; expected one of {MODEL_ROLES}")
    settings = settings or get_settings()
    base_url = settings.model_role_value(role, "BASE_URL") or settings.MODEL_DEFAULT_BASE_URL
    proxy_url = settings.model_role_value(role, "PROXY_URL") or settings.MODEL_DEFAULT_PROXY_URL
    timeout_s = settings.model_role_value(role, "TIMEOUT_S") or _DEFAULT_TIMEOUTS_S[role]
    max_tokens = (
        getattr(settings, f"MODEL_{role.upper()}_MAX_TOKENS", None)
        or settings.MODEL_DEFAULT_MAX_TOKENS
        or _DEFAULT_MAX_TOKENS.get(role)
    )
    return RoleConfig(
        role=role,
        provider=settings.effective_model_provider,
        base_url=str(base_url).rstrip("/"),
        api_key=settings.model_role_api_key(role),
        model=str(settings.model_role_value(role, "MODEL")),
        proxy_url=str(proxy_url) if proxy_url else None,
        timeout_s=float(timeout_s),
        max_tokens=int(max_tokens) if max_tokens else None,
    )


def all_role_configs(settings: Settings | None = None) -> list[RoleConfig]:
    settings = settings or get_settings()
    return [get_role_config(role, settings) for role in MODEL_ROLES]
