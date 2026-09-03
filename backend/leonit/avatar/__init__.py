"""ИИ-аватар интервьюера: задел за фиче-флагом.

Комната интервью показывает вопрос текстом и озвучкой (TTS); аватар — это
видеоклип «интервьюера», который произносит вопрос. Пока ни один реальный
провайдер не подключён, работает ``NullAvatarProvider``, и комната показывает
персону «ИИ-интервьюер LeonIT» с индикатором речи, синхронизированным с TTS.

Точка входа — ``get_avatar_provider()`` (``registry.py``), протокол и типы —
``base.py``, кэш готовых клипов по хешу текста и голоса — ``cache.py``.
Включение: ``AVATAR_ENABLED=true`` и ``AVATAR_PROVIDER=<имя из реестра>``.
"""

from leonit.avatar.base import AvatarClip, AvatarProvider, NullAvatarProvider
from leonit.avatar.cache import avatar_cache_key, get_or_render
from leonit.avatar.registry import get_avatar_provider, register_avatar_provider

__all__ = [
    "AvatarClip",
    "AvatarProvider",
    "NullAvatarProvider",
    "avatar_cache_key",
    "get_avatar_provider",
    "get_or_render",
    "register_avatar_provider",
]
