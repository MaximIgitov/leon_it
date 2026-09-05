"""ИИ-аватар: реестр провайдеров, кэш клипов и поле ``avatar`` в комнате."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from leonit.avatar import (
    AvatarClip,
    NullAvatarProvider,
    avatar_cache_key,
    get_avatar_provider,
    get_or_render,
)
from leonit.avatar.cache import _render_locks
from leonit.core.config import Settings, get_settings
from leonit.core.storage import LocalStorage
from leonit.interviews import service as room_service
from tests.test_interview_room import _consented


class StubAvatar:
    enabled = True

    def __init__(
        self,
        *,
        clip: bool = True,
        delay_s: float = 0.0,
        fail: bool = False,
        name: str | None = None,
    ) -> None:
        # Кэш клипов общий на весь прогон (MEDIA_ROOT один): у каждого стаба своё
        # имя провайдера, чтобы тесты не подбирали клипы друг друга.
        self.name = name or f"stub-{uuid.uuid4().hex[:8]}"
        self.calls = 0
        self.clip = clip
        self.delay_s = delay_s
        self.fail = fail

    async def render(self, question_text: str, voice: str | None, language: str):
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("provider down")
        if not self.clip:
            return None
        return AvatarClip(url=f"https://cdn.example/{voice}/{self.calls}.mp4", duration_s=4.2)


def test_default_provider_is_null() -> None:
    provider = get_avatar_provider(Settings())
    assert isinstance(provider, NullAvatarProvider)
    assert provider.enabled is False


async def test_cache_renders_once_per_text_voice_language(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    provider = StubAvatar(name="stub")
    first = await get_or_render(storage, provider, "Расскажите о себе", "alloy", "ru")
    second = await get_or_render(storage, provider, "Расскажите о себе", "alloy", "ru")
    assert first is not None and first == second
    assert provider.calls == 1
    assert await storage.exists(avatar_cache_key("Расскажите о себе", "alloy", "ru", "stub"))
    # Другой голос — другой клип; другой язык — тоже.
    other_voice = await get_or_render(storage, provider, "Расскажите о себе", "nova", "ru")
    other_lang = await get_or_render(storage, provider, "Расскажите о себе", "alloy", "en")
    assert other_voice is not None and other_voice.url != first.url
    assert other_lang is not None and other_lang.url not in (first.url, other_voice.url)
    assert provider.calls == 3
    assert len(_render_locks) == 0


async def test_cache_does_not_store_refusal(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    provider = StubAvatar(clip=False, name="stub")
    assert await get_or_render(storage, provider, "Вопрос", None, "ru") is None
    assert await get_or_render(storage, provider, "Вопрос", None, "ru") is None
    assert provider.calls == 2
    assert not await storage.exists(avatar_cache_key("Вопрос", None, "ru", "stub"))


async def test_concurrent_misses_render_once(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    provider = StubAvatar(delay_s=0.05)
    results = await asyncio.gather(
        *(get_or_render(storage, provider, "Вопрос", "alloy", "ru") for _ in range(5))
    )
    assert provider.calls == 1
    assert len({clip.url for clip in results if clip}) == 1


async def _revealed(client: AsyncClient) -> tuple[str, dict]:
    _, _, link, _ = await _consented(client)
    assert (await client.post(f"/api/public/invitations/{link}/start", json={})).status_code == 200
    response = await client.post(f"/api/public/invitations/{link}/questions/0/reveal")
    assert response.status_code == 200, response.text
    return link, response.json()


async def test_avatar_disabled_by_default(client: AsyncClient) -> None:
    _, body = await _revealed(client)
    assert body["avatar"] == {"enabled": False, "clip_url": None, "duration_s": None}


async def test_null_provider_reports_disabled_even_with_flag(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    _, body = await _revealed(client)
    assert body["avatar"]["enabled"] is False and body["avatar"]["clip_url"] is None


async def test_stub_provider_clip_is_served_and_cached(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    stub = StubAvatar()
    monkeypatch.setattr(room_service, "get_avatar_provider", lambda settings=None: stub)
    link, body = await _revealed(client)
    assert body["avatar"]["enabled"] is True
    assert body["avatar"]["clip_url"] == "https://cdn.example/nova/1.mp4", body
    assert body["avatar"]["duration_s"] == 4.2
    again = (await client.post(f"/api/public/invitations/{link}/questions/0/reveal")).json()
    assert again["avatar"]["clip_url"] == body["avatar"]["clip_url"]
    assert stub.calls == 1
    # Озвучка TTS по-прежнему отдаётся: клиент сам решает, что воспроизводить.
    assert body["audio_url"].startswith("/api/media/")


async def test_provider_failure_keeps_interview_going(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    monkeypatch.setattr(
        room_service, "get_avatar_provider", lambda settings=None: StubAvatar(fail=True)
    )
    _, body = await _revealed(client)
    assert body["question"]["text"] == "Расскажите о себе"
    assert body["avatar"] == {"enabled": True, "clip_url": None, "duration_s": None}
