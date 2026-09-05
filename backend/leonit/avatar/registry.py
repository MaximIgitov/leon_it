"""Реестр провайдеров аватара.

Как добавить реального провайдера (HeyGen, D-ID, Synthesia и т. п.):

1. Реализовать протокол ``AvatarProvider`` в ``leonit/avatar/providers/<name>.py``:
   ``render`` отправляет текст вопроса в API провайдера через
   ``httpx.AsyncClient(timeout=...)``, дожидается готовности клипа (у большинства
   сервисов рендер асинхронный: создать задачу → опрашивать статус → получить
   URL) и возвращает ``AvatarClip``. Ключи API — только из настроек
   (``AVATAR_<NAME>_API_KEY``), а если их нужно хранить в БД — через
   ``leonit.core.crypto.SecretBox``.
2. Зарегистрировать фабрику: ``register_avatar_provider("heygen", HeyGenAvatar.from_settings)``
   в модуле провайдера и импортировать модуль здесь (или из ``leonit.avatar``).
3. Добавить имя в ``AvatarProvider`` Literal в ``leonit.core.config`` и задать
   ``AVATAR_PROVIDER=heygen``, ``AVATAR_ENABLED=true``.

Кэш (``cache.py``) уже общий: повторный вопрос с тем же голосом и языком не
рендерится заново — важно, потому что рендер аватара стоит дороже TTS.
"""

from __future__ import annotations

from collections.abc import Callable

from leonit.avatar.base import AvatarProvider, NullAvatarProvider
from leonit.core.config import Settings, get_settings

ProviderFactory = Callable[[Settings], AvatarProvider]

_factories: dict[str, ProviderFactory] = {"none": lambda _settings: NullAvatarProvider()}


def register_avatar_provider(name: str, factory: ProviderFactory) -> None:
    _factories[name] = factory


def registered_avatar_providers() -> list[str]:
    return sorted(_factories)


def get_avatar_provider(settings: Settings | None = None) -> AvatarProvider:
    settings = settings or get_settings()
    factory = _factories.get(settings.AVATAR_PROVIDER)
    if factory is None:
        raise ValueError(
            f"unknown avatar provider {settings.AVATAR_PROVIDER!r}; "
            f"registered: {registered_avatar_providers()}"
        )
    return factory(settings)


def avatar_available(settings: Settings | None = None) -> bool:
    """Можно ли включить аватар на этом сервере: флаг и настроенный провайдер."""
    settings = settings or get_settings()
    if not settings.AVATAR_ENABLED:
        return False
    try:
        return get_avatar_provider(settings).enabled
    except ValueError:
        return False
