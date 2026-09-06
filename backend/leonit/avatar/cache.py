"""Кэш клипов аватара — по образцу ``leonit.ai.tts_cache``.

Ключ — хеш от текста вопроса, голоса, языка, имени провайдера и его «варианта»
(облик и кадр аватара): смена любого из них даёт новый рендер, а правка текста
вопроса инвалидирует старый клип.
В хранилище лежит маленький JSON-манифест с результатом рендера, а не сам
файл: у большинства провайдеров клип живёт на их CDN. Провайдер, который
кладёт видео к нам, заполняет ``storage_key`` — тогда URL переподписывается
при каждой выдаче, и срок подписи не «замораживается» в кэше.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from leonit.avatar.base import AvatarClip, AvatarProvider
from leonit.core.logging import get_logger
from leonit.core.storage import KeyLocks, Storage

log = get_logger(__name__)

# Одновременный промах из нескольких комнат — рендерит один, остальные ждут.
_render_locks = KeyLocks()


def avatar_cache_key(
    text: str, voice: str | None, language: str, provider: str, variant: str = ""
) -> str:
    """``variant`` — облик и кадр у провайдера (аватар, движок, формат): смена любого из
    них даёт новый ключ, иначе после переключения аватара отдавались бы старые клипы."""
    raw = f"{text}|{voice or ''}|{language}|{provider}"
    if variant:
        raw += f"|{variant}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"avatar/{digest}.json"


def _key(provider: AvatarProvider, text: str, voice: str | None, language: str) -> str:
    return avatar_cache_key(text, voice, language, provider.name, getattr(provider, "variant", ""))


async def _read_manifest(storage: Storage, key: str) -> AvatarClip | None:
    chunks: list[bytes] = []
    async for chunk in storage.open_range(key):
        chunks.append(chunk)
    try:
        data: dict[str, Any] = json.loads(b"".join(chunks).decode("utf-8"))
        return AvatarClip(
            url=str(data["url"]),
            duration_s=data.get("duration_s"),
            storage_key=data.get("storage_key"),
        )
    except (ValueError, KeyError, TypeError):
        # Битый манифест — считаем промахом и перерендерим.
        log.warning("avatar.cache.corrupt key=%s", key)
        return None


async def lookup(
    storage: Storage,
    provider: AvatarProvider,
    text: str,
    voice: str | None,
    language: str,
) -> AvatarClip | None:
    """Только кэш, без рендера: так комната работает с провайдерами, где рендер долгий."""
    key = _key(provider, text, voice, language)
    if await storage.exists(key):
        return await _read_manifest(storage, key)
    return None


async def get_or_render(
    storage: Storage,
    provider: AvatarProvider,
    text: str,
    voice: str | None,
    language: str,
) -> AvatarClip | None:
    """Вернуть клип из кэша или отрендерить; ``None`` — провайдер клип не дал."""
    key = _key(provider, text, voice, language)
    cached = await lookup(storage, provider, text, voice, language)
    if cached is not None:
        return cached
    async with _render_locks(key):
        if await storage.exists(key):
            cached = await _read_manifest(storage, key)
            if cached is not None:
                return cached
        clip = await provider.render(text, voice, language)
        if clip is None:
            # Отказ не кэшируем: следующий кандидат может получить клип.
            return None
        manifest = {
            "url": clip.url,
            "duration_s": clip.duration_s,
            "storage_key": clip.storage_key,
            "provider": provider.name,
        }
        await storage.put(key, json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    return clip
