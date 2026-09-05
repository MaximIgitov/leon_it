"""ИИ-аватар интервьюера: опция вакансии за фиче-флагом сервера.

Комната интервью показывает вопрос текстом и озвучкой (TTS); аватар — это
видеоклип «интервьюера», который произносит вопрос. Без провайдера работает
``NullAvatarProvider``, и комната показывает персону «ИИ-интервьюер LeonIT» с
индикатором речи, синхронизированным с TTS. Реальный провайдер — HeyGen
(``providers/heygen.py``): рендер долгий и платный, поэтому клипы готовятся
заранее задачей ``avatar.prewarm`` (``jobs.py``), а включается аватар отдельно
для каждой вакансии (``avatar_enabled`` в настройках интервью).

Точка входа — ``get_avatar_provider()`` (``registry.py``), протокол и типы —
``base.py``, кэш готовых клипов по хешу текста и голоса — ``cache.py``.
Включение на сервере: ``AVATAR_ENABLED=true``, ``AVATAR_PROVIDER=heygen`` и
``AVATAR_HEYGEN_API_KEY``.
"""

from leonit.avatar.base import AvatarClip, AvatarProvider, NullAvatarProvider
from leonit.avatar.cache import avatar_cache_key, get_or_render, lookup
from leonit.avatar.providers import heygen as _heygen  # noqa: F401 — регистрирует провайдера
from leonit.avatar.registry import (
    avatar_available,
    get_avatar_provider,
    register_avatar_provider,
)

__all__ = [
    "AvatarClip",
    "AvatarProvider",
    "NullAvatarProvider",
    "avatar_available",
    "avatar_cache_key",
    "get_avatar_provider",
    "get_or_render",
    "lookup",
    "register_avatar_provider",
]
