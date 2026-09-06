"""ИИ-аватар: реестр провайдеров, кэш клипов, HeyGen, прогрев и поле ``avatar`` в комнате."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leonit.avatar import (
    AvatarClip,
    NullAvatarProvider,
    avatar_available,
    avatar_cache_key,
    get_avatar_provider,
    get_or_render,
)
from leonit.avatar import jobs as avatar_jobs
from leonit.avatar.cache import _render_locks
from leonit.avatar.jobs import PREWARM_KIND
from leonit.avatar.providers.heygen import HeyGenAvatar, HeyGenError
from leonit.core.config import Settings, get_settings
from leonit.core.db import get_session_maker
from leonit.core.storage import LocalStorage, get_storage
from leonit.interviews import service as room_service
from leonit.jobs.models import Job
from leonit.jobs.registry import JobContext
from tests.helpers import bearer, register
from tests.test_candidates import _invite, _token


class StubAvatar:
    enabled = True

    def __init__(
        self,
        *,
        clip: bool = True,
        delay_s: float = 0.0,
        fail: bool = False,
        name: str | None = None,
        background: bool = False,
    ) -> None:
        # Кэш клипов общий на весь прогон (MEDIA_ROOT один): у каждого стаба своё
        # имя провайдера, чтобы тесты не подбирали клипы друг друга.
        self.name = name or f"stub-{uuid.uuid4().hex[:8]}"
        self.calls = 0
        self.clip = clip
        self.delay_s = delay_s
        self.fail = fail
        # Как у HeyGen: рендер долгий, комната берёт только готовые клипы.
        self.background_render = background

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


async def _in_room(client: AsyncClient, *, avatar: bool = True) -> tuple[str, str]:
    """Опубликованная вакансия (аватар по настройке), кандидат согласился и начал интервью."""
    _, token = await register(client, organization_name="Napoleon IT")
    response = await client.post(
        "/api/vacancies",
        json={"title": "Python-разработчик", "description": "Бэкенд"},
        headers=bearer(token),
    )
    vacancy = response.json()
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={"questions": [{"text": "Расскажите о себе"}, {"text": "Что такое GIL?"}]},
        headers=bearer(token),
    )
    if avatar:
        patched = await client.patch(
            f"/api/vacancies/{vacancy['id']}",
            json={"settings": {"avatar_enabled": True}},
            headers=bearer(token),
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["settings"]["avatar_enabled"] is True
    published = await client.post(f"/api/vacancies/{vacancy['id']}/publish", headers=bearer(token))
    assert published.status_code == 200, published.text
    interview = await _invite(client, token, vacancy["id"], "cand@example.com")
    link = _token(interview["link"])
    page = (await client.get(f"/api/public/invitations/{link}")).json()
    consent = await client.post(
        f"/api/public/invitations/{link}/consent",
        json={
            "full_name": "Иван Кандидат",
            "email": "cand@example.com",
            "personal_data_accepted": True,
            "privacy_policy_accepted": True,
            "document_versions": {d["slug"]: d["version"] for d in page["consent_documents"]},
        },
    )
    assert consent.status_code in (200, 201), consent.text
    assert (await client.post(f"/api/public/invitations/{link}/start", json={})).status_code == 200
    return link, vacancy["id"]


async def _revealed(client: AsyncClient, *, avatar: bool = True) -> tuple[str, dict]:
    link, _ = await _in_room(client, avatar=avatar)
    response = await client.post(f"/api/public/invitations/{link}/questions/0/reveal")
    assert response.status_code == 200, response.text
    return link, response.json()


async def _prewarm_jobs(vacancy_id: str) -> list[Job]:
    async with get_session_maker()() as session:
        rows = await session.scalars(select(Job).where(Job.kind == PREWARM_KIND))
        return [job for job in rows if job.payload.get("vacancy_id") == vacancy_id]


def _ctx() -> JobContext:
    async def heartbeat() -> bool:
        return True

    return JobContext(
        job_id=uuid.uuid4(),
        kind=PREWARM_KIND,
        attempt=1,
        worker_id="test",
        session_maker=get_session_maker(),
        _heartbeat=heartbeat,
    )


async def test_avatar_disabled_by_default(client: AsyncClient) -> None:
    _, body = await _revealed(client, avatar=False)
    assert body["avatar"] == {"enabled": False, "clip_url": None, "duration_s": None}


async def test_vacancy_without_avatar_keeps_persona_even_with_provider(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Аватар платный: без явного включения у вакансии провайдер не вызывается.
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    stub = StubAvatar()
    monkeypatch.setattr(room_service, "get_avatar_provider", lambda settings=None: stub)
    _, body = await _revealed(client, avatar=False)
    assert body["avatar"] == {"enabled": False, "clip_url": None, "duration_s": None}
    assert stub.calls == 0


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


# ------------------------------------------------- долгий рендер и прогрев


async def test_background_provider_serves_cached_clips_only_and_schedules_prewarm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    stub = StubAvatar(background=True)
    monkeypatch.setattr(room_service, "get_avatar_provider", lambda settings=None: stub)
    link, vacancy_id = await _in_room(client)
    # Комната рендер не запускает: кандидат видит персону, прогрев стоит в очереди (без дублей).
    first = (await client.post(f"/api/public/invitations/{link}/questions/0/reveal")).json()
    assert first["avatar"] == {"enabled": True, "clip_url": None, "duration_s": None}
    assert stub.calls == 0
    jobs = await _prewarm_jobs(vacancy_id)
    assert len(jobs) == 1 and jobs[0].dedupe_key == f"{PREWARM_KIND}:{vacancy_id}"
    # Прогрев положил клип в кэш — комната отдаёт его без рендера.
    clip = await get_or_render(get_storage(), stub, "Расскажите о себе", "nova", "ru")
    assert clip is not None and stub.calls == 1
    again = (await client.post(f"/api/public/invitations/{link}/questions/0/reveal")).json()
    assert again["avatar"] == {"enabled": True, "clip_url": clip.url, "duration_s": 4.2}
    assert stub.calls == 1


async def test_prewarm_job_renders_each_question_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    stub = StubAvatar(background=True)
    monkeypatch.setattr(avatar_jobs, "get_avatar_provider", lambda settings=None: stub)
    _, vacancy_id = await _in_room(client)
    result = await avatar_jobs.prewarm({"vacancy_id": vacancy_id}, _ctx())
    assert result == {"rendered": 2, "cached": 0, "failed": 0}
    assert stub.calls == 2
    again = await avatar_jobs.prewarm({"vacancy_id": vacancy_id}, _ctx())
    assert again == {"rendered": 0, "cached": 2, "failed": 0}
    assert stub.calls == 2


async def test_prewarm_job_skips_vacancy_with_avatar_off(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    stub = StubAvatar(background=True)
    monkeypatch.setattr(avatar_jobs, "get_avatar_provider", lambda settings=None: stub)
    _, vacancy_id = await _in_room(client, avatar=False)
    assert await avatar_jobs.prewarm({"vacancy_id": vacancy_id}, _ctx()) == {
        "skipped": "avatar_off"
    }
    assert stub.calls == 0


async def test_prewarm_job_fails_when_nothing_renders(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    monkeypatch.setattr(
        avatar_jobs, "get_avatar_provider", lambda settings=None: StubAvatar(fail=True)
    )
    _, vacancy_id = await _in_room(client)
    with pytest.raises(RuntimeError):
        await avatar_jobs.prewarm({"vacancy_id": vacancy_id}, _ctx())


async def test_publish_and_settings_changes_schedule_prewarm(client: AsyncClient) -> None:
    _, token = await register(client, organization_name="Napoleon IT")
    vacancy = (
        await client.post(
            "/api/vacancies",
            json={"title": "Go", "description": "Платформа"},
            headers=bearer(token),
        )
    ).json()
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={"questions": [{"text": "Расскажите о Go"}]},
        headers=bearer(token),
    )
    # Аватар выключен — публикация ничего не ставит.
    assert (
        await client.post(f"/api/vacancies/{vacancy['id']}/publish", headers=bearer(token))
    ).status_code == 200
    assert await _prewarm_jobs(vacancy["id"]) == []
    # Включили у опубликованной — прогрев поставлен один раз; смена вопросов дублей не создаёт.
    patched = await client.patch(
        f"/api/vacancies/{vacancy['id']}",
        json={"settings": {"avatar_enabled": True}},
        headers=bearer(token),
    )
    assert patched.status_code == 200, patched.text
    assert len(await _prewarm_jobs(vacancy["id"])) == 1
    await client.put(
        f"/api/vacancies/{vacancy['id']}/questions",
        json={"questions": [{"text": "Расскажите о горутинах"}]},
        headers=bearer(token),
    )
    assert len(await _prewarm_jobs(vacancy["id"])) == 1


async def test_vacancy_detail_reports_avatar_availability(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = await register(client, organization_name="Napoleon IT")
    vacancy = (
        await client.post("/api/vacancies", json={"title": "Go"}, headers=bearer(token))
    ).json()
    assert vacancy["avatar_available"] is False
    settings = get_settings()
    monkeypatch.setattr(settings, "AVATAR_ENABLED", True)
    monkeypatch.setattr(settings, "AVATAR_PROVIDER", "heygen")
    monkeypatch.setattr(settings, "AVATAR_HEYGEN_API_KEY", "key")
    detail = (await client.get(f"/api/vacancies/{vacancy['id']}", headers=bearer(token))).json()
    assert detail["avatar_available"] is True


# ------------------------------------------------------------------- HeyGen


def _heygen(tmp_path: Path, handler: Callable[..., httpx.Response], **overrides) -> HeyGenAvatar:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://heygen.test")
    params: dict = {
        "api_key": "key-1",
        "avatar_id": "Look_1",
        "voice_id": "voice-ru",
        "storage": LocalStorage(tmp_path),
        "http": http,
        "poll_s": 0.01,
        "timeout_s": 5.0,
    }
    params.update(overrides)
    return HeyGenAvatar(**params)


def _heygen_api(polls_until_done: int = 2, final_status: str = "completed"):
    calls: list[httpx.Request] = []
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST" and request.url.path == "/v3/videos":
            return httpx.Response(200, json={"data": {"video_id": "v_1", "status": "waiting"}})
        if request.url.path == "/v3/videos/v_1":
            state["polls"] += 1
            if state["polls"] < polls_until_done:
                return httpx.Response(200, json={"data": {"status": "processing"}})
            if final_status == "completed":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "status": "completed",
                            "video_url": "https://cdn.heygen.test/v_1.mp4",
                            "duration": 12.5,
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "failed",
                        "failure_code": "rendering_failed",
                        "failure_message": "Avatar rendering timed out",
                    }
                },
            )
        if request.url.host == "cdn.heygen.test":
            return httpx.Response(200, content=b"mp4-bytes")
        if request.url.path == "/v3/users/me":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "billing_type": "wallet",
                        "wallet": {"currency": "usd", "remaining_balance": 9.5},
                    }
                },
            )
        return httpx.Response(404, json={"error": "nope"})

    return handler, calls


async def test_heygen_renders_downloads_and_stores_clip(tmp_path: Path) -> None:
    handler, calls = _heygen_api()
    provider = _heygen(tmp_path, handler)
    assert provider.enabled and provider.background_render and provider.name == "heygen"
    clip = await provider.render("Расскажите   о себе\n", "nova", "ru")
    assert clip is not None and clip.storage_key and clip.storage_key.startswith("avatar/heygen/")
    assert clip.duration_s == 12.5 and clip.url.startswith("/api/media/")
    assert await provider.storage.exists(clip.storage_key)
    submit = calls[0]
    body = json.loads(submit.content)
    assert body["type"] == "avatar" and body["avatar_id"] == "Look_1"
    assert body["voice_id"] == "voice-ru" and body["script"] == "Расскажите о себе"
    # Экономия: самый дешёвый движок, 720p, квадрат под сцену комнаты.
    assert body["engine"] == {"type": "avatar_iii"}
    assert body["resolution"] == "720p" and body["aspect_ratio"] == "1:1"
    assert submit.headers["x-api-key"] == "key-1"
    assert submit.headers["Idempotency-Key"].startswith("leonit-")
    download = next(call for call in calls if call.url.host == "cdn.heygen.test")
    assert "x-api-key" not in download.headers
    # Тот же текст — тот же ключ идемпотентности: повтор не создаст второе видео.
    await provider.render("Расскажите о себе", "nova", "ru")
    resubmit = [call for call in calls if call.method == "POST"][1]
    assert resubmit.headers["Idempotency-Key"] == submit.headers["Idempotency-Key"]


async def test_heygen_failed_render_gives_no_clip(tmp_path: Path) -> None:
    handler, calls = _heygen_api(final_status="failed")
    provider = _heygen(tmp_path, handler)
    assert await provider.render("Вопрос", None, "ru") is None
    assert not any(call.url.host == "cdn.heygen.test" for call in calls)


async def test_heygen_skips_long_text_without_calls(tmp_path: Path) -> None:
    handler, calls = _heygen_api()
    provider = _heygen(tmp_path, handler, max_text_chars=20)
    assert (
        await provider.render("Очень длинный вопрос, который дороже, чем стоит", None, "ru") is None
    )
    assert calls == []


async def test_heygen_times_out_when_render_hangs(tmp_path: Path) -> None:
    handler, _ = _heygen_api(polls_until_done=10_000)
    provider = _heygen(tmp_path, handler, timeout_s=0.05)
    with pytest.raises(HeyGenError):
        await provider.render("Вопрос", None, "ru")


async def test_heygen_http_error_is_reported(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "unauthorized"}})

    with pytest.raises(HeyGenError, match="HTTP 401"):
        await _heygen(tmp_path, handler).render("Вопрос", None, "ru")


async def test_heygen_balance_registry_and_availability(tmp_path: Path) -> None:
    handler, _ = _heygen_api()
    assert await _heygen(tmp_path, handler).balance_usd() == 9.5
    assert _heygen(tmp_path, handler, api_key=None).enabled is False
    settings = Settings(AVATAR_ENABLED=True, AVATAR_PROVIDER="heygen", AVATAR_HEYGEN_API_KEY="k")
    provider = get_avatar_provider(settings)
    assert isinstance(provider, HeyGenAvatar) and provider.enabled and provider.background_render
    assert avatar_available(settings) is True
    assert avatar_available(Settings(AVATAR_ENABLED=True, AVATAR_PROVIDER="heygen")) is False
    assert avatar_available(Settings(AVATAR_ENABLED=True)) is False
    assert avatar_available(Settings(AVATAR_PROVIDER="heygen", AVATAR_HEYGEN_API_KEY="k")) is False


async def test_new_vacancy_enables_avatar_when_provider_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Аватар включён по умолчанию, когда провайдер настроен; без него — выключен."""
    from leonit.avatar import registry as avatar_registry

    _, owner = await register(client)
    plain = await client.post(
        "/api/vacancies", json={"title": "Без провайдера"}, headers=bearer(owner)
    )
    assert plain.json()["settings"]["avatar_enabled"] is False

    monkeypatch.setattr(get_settings(), "AVATAR_ENABLED", True)
    monkeypatch.setattr(avatar_registry, "get_avatar_provider", lambda settings=None: StubAvatar())
    with_avatar = await client.post(
        "/api/vacancies", json={"title": "С провайдером"}, headers=bearer(owner)
    )
    assert with_avatar.json()["settings"]["avatar_enabled"] is True
