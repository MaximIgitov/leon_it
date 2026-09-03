from __future__ import annotations

from pathlib import Path

from leonit.ai.providers.base import AudioResult, TTSProvider
from leonit.ai.tts_cache import get_or_synthesize, tts_cache_key
from leonit.core.storage import LocalStorage


class CountingTTS(TTSProvider):
    model = "tts-1"

    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, text, *, voice=None, audio_format="mp3") -> AudioResult:
        self.calls += 1
        return AudioResult(data=f"{voice}:{text}".encode(), content_type="audio/mpeg")


async def test_second_call_hits_cache(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    tts = CountingTTS()
    key, content_type = await get_or_synthesize(storage, tts, "Расскажите о себе")
    assert key.startswith("tts/") and key.endswith(".mp3")
    assert content_type == "audio/mpeg"
    assert tts.calls == 1
    assert await storage.size(key) == len("alloy:Расскажите о себе".encode())

    again_key, again_type = await get_or_synthesize(storage, tts, "Расскажите о себе")
    assert again_key == key and again_type == "audio/mpeg"
    assert tts.calls == 1


async def test_voice_text_and_model_change_the_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    tts = CountingTTS()
    key_default, _ = await get_or_synthesize(storage, tts, "Вопрос")
    key_voice, _ = await get_or_synthesize(storage, tts, "Вопрос", voice="nova")
    key_text, _ = await get_or_synthesize(storage, tts, "Вопрос?")
    assert len({key_default, key_voice, key_text}) == 3
    assert tts.calls == 3
    assert tts_cache_key("Вопрос", "alloy", "tts-1", "mp3") == key_default
    assert tts_cache_key("Вопрос", "alloy", "tts-2", "mp3") != key_default
