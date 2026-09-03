"""Кэш озвучки вопросов.

Один и тот же вопрос слышат все кандидаты по вакансии, а синтез стоит денег и
секунды. Ключ — хеш от текста, голоса и модели: смена любого из них даёт новый
файл, а правка текста вопроса автоматически «инвалидирует» старую озвучку.
"""

from __future__ import annotations

import hashlib

from leonit.ai.providers.base import AUDIO_CONTENT_TYPES, TTSProvider
from leonit.core.storage import Storage


def tts_cache_key(text: str, voice: str, model: str, audio_format: str) -> str:
    digest = hashlib.sha256(f"{text}|{voice}|{model}".encode()).hexdigest()
    return f"tts/{digest}.{audio_format}"


async def get_or_synthesize(
    storage: Storage,
    tts: TTSProvider,
    text: str,
    voice: str | None = None,
    *,
    audio_format: str = "mp3",
) -> tuple[str, str]:
    """Вернуть ключ хранилища и Content-Type; синтезировать только при промахе."""
    voice = voice or tts.default_voice
    actual_format = tts.resolve_format(audio_format)
    key = tts_cache_key(text, voice, tts.model, actual_format)
    content_type = AUDIO_CONTENT_TYPES.get(actual_format, "application/octet-stream")
    if await storage.exists(key):
        return key, content_type
    result = await tts.synthesize(text, voice=voice, audio_format=audio_format)
    await storage.put(key, result.data)
    return key, result.content_type or content_type
