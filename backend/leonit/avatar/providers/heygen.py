"""HeyGen: клип с вопросом через ``POST /v3/videos`` с кошелька pay-as-you-go.

Рендер у HeyGen асинхронный и занимает минуты, поэтому провайдер помечен
``background_render``: комната кандидата не ждёт, клипы готовит задача
``avatar.prewarm`` при публикации вакансии (см. ``leonit.avatar.jobs``).
Готовый файл скачивается в наше хранилище: подписанная ссылка HeyGen живёт
недолго, а кэш клипов постоянный.

Экономия: движок ``avatar_iii`` (самый дешёвый, около доллара за минуту
готового видео), 720p, квадрат 1:1 под сцену комнаты; ``Idempotency-Key`` от
текста, образа и голоса, поэтому повтор запроса в течение суток не создаёт
второе видео и не списывает деньги дважды; вопрос длиннее лимита не
рендерится. Ключ только из настроек (``AVATAR_HEYGEN_API_KEY``).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from leonit.avatar.base import AvatarClip
from leonit.avatar.registry import register_avatar_provider
from leonit.core.config import Settings
from leonit.core.logging import get_logger
from leonit.core.storage import Storage, get_storage
from leonit.media.service import sign_media_url

log = get_logger(__name__)

TERMINAL_STATUSES = frozenset({"completed", "failed"})


class HeyGenError(RuntimeError):
    """Сеть, HTTP-статус или таймаут рендера: комната и прогрев логируют и живут дальше."""


def clip_fingerprint(text: str, avatar_id: str, voice_id: str, engine: str, resolution: str) -> str:
    """Отпечаток клипа: он же ключ идемпотентности у HeyGen и имя файла в хранилище."""
    raw = f"{text}|{avatar_id}|{voice_id}|{engine}|{resolution}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class HeyGenAvatar:
    api_key: str | None
    avatar_id: str
    voice_id: str
    storage: Storage
    base_url: str = "https://api.heygen.com"
    engine: str = "avatar_iii"
    resolution: str = "720p"
    timeout_s: float = 420.0
    poll_s: float = 5.0
    max_text_chars: int = 600
    # Тесты подставляют клиент с MockTransport; в бою клиент создаётся на каждый рендер.
    http: httpx.AsyncClient | None = None

    name = "heygen"
    background_render = True

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.avatar_id and self.voice_id)

    @classmethod
    def from_settings(cls, settings: Settings) -> HeyGenAvatar:
        return cls(
            api_key=settings.AVATAR_HEYGEN_API_KEY,
            avatar_id=settings.AVATAR_HEYGEN_AVATAR_ID,
            voice_id=settings.AVATAR_HEYGEN_VOICE_ID,
            storage=get_storage(),
            base_url=settings.AVATAR_HEYGEN_BASE_URL,
            engine=settings.AVATAR_HEYGEN_ENGINE,
            resolution=settings.AVATAR_HEYGEN_RESOLUTION,
            timeout_s=settings.AVATAR_HEYGEN_TIMEOUT_S,
            poll_s=settings.AVATAR_HEYGEN_POLL_S,
            max_text_chars=settings.AVATAR_MAX_TEXT_CHARS,
        )

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.http is not None:
            yield self.http
            return
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0, read=90.0),
            follow_redirects=True,
        ) as client:
            yield client

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key or "", "accept": "application/json"}

    @staticmethod
    def _data(response: httpx.Response, step: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise HeyGenError(f"HeyGen {step}: HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as error:
            raise HeyGenError(f"HeyGen {step}: ответ не JSON") from error
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else {}

    async def render(
        self, question_text: str, voice: str | None, language: str
    ) -> AvatarClip | None:
        """Отправить вопрос на рендер, дождаться клипа и положить его в хранилище.

        ``voice`` комнаты (голос TTS) не используется: у HeyGen свой голос из
        настроек, а кэш клипов и так различает голоса по ключу.
        """
        if not self.enabled:
            return None
        text = " ".join(question_text.split())
        if not text:
            return None
        if len(text) > self.max_text_chars:
            log.warning(
                "avatar.heygen.skip_long_text chars=%s limit=%s", len(text), self.max_text_chars
            )
            return None
        fingerprint = clip_fingerprint(
            text, self.avatar_id, self.voice_id, self.engine, self.resolution
        )
        storage_key = f"avatar/heygen/{fingerprint[:32]}.mp4"
        async with self._session() as client:
            video_id = await self._submit(client, text, fingerprint)
            status = await self._wait(client, video_id)
            video_url = status.get("video_url")
            if status.get("status") != "completed" or not video_url:
                log.warning(
                    "avatar.heygen.failed video=%s code=%s message=%s",
                    video_id,
                    status.get("failure_code"),
                    status.get("failure_message"),
                )
                return None
            await self._download(client, str(video_url), storage_key)
        duration = status.get("duration")
        log.info(
            "avatar.heygen.rendered video=%s duration=%s key=%s", video_id, duration, storage_key
        )
        return AvatarClip(
            url=sign_media_url(storage_key, ttl_s=1800, content_type="video/mp4"),
            duration_s=float(duration) if isinstance(duration, (int, float)) else None,
            storage_key=storage_key,
        )

    async def _submit(self, client: httpx.AsyncClient, text: str, fingerprint: str) -> str:
        body = {
            "type": "avatar",
            "avatar_id": self.avatar_id,
            "script": text,
            "voice_id": self.voice_id,
            "engine": {"type": self.engine},
            "resolution": self.resolution,
            "aspect_ratio": "1:1",
            "title": f"LeonIT вопрос {fingerprint[:8]}",
        }
        headers = {**self._headers(), "Idempotency-Key": f"leonit-{fingerprint[:48]}"}
        response = await client.post("/v3/videos", json=body, headers=headers)
        data = self._data(response, "submit")
        video_id = data.get("video_id")
        if not video_id:
            raise HeyGenError("HeyGen submit: в ответе нет video_id")
        return str(video_id)

    async def _wait(self, client: httpx.AsyncClient, video_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_s
        while True:
            response = await client.get(f"/v3/videos/{video_id}", headers=self._headers())
            data = self._data(response, "status")
            if data.get("status") in TERMINAL_STATUSES:
                return data
            if time.monotonic() >= deadline:
                raise HeyGenError(f"HeyGen не отрендерил клип {video_id} за {self.timeout_s:.0f} с")
            await asyncio.sleep(self.poll_s)

    async def _download(self, client: httpx.AsyncClient, url: str, storage_key: str) -> None:
        # Подписанная ссылка на CDN: без нашего ключа и без базового адреса API.
        response = await client.get(url)
        if response.status_code >= 400:
            raise HeyGenError(f"HeyGen download: HTTP {response.status_code}")
        if not response.content:
            raise HeyGenError("HeyGen download: пустой файл")
        await self.storage.put(storage_key, response.content)

    async def balance_usd(self) -> float | None:
        """Остаток кошелька pay-as-you-go: пишется в результат прогрева, чтобы видеть расход."""
        async with self._session() as client:
            response = await client.get("/v3/users/me", headers=self._headers())
            data = self._data(response, "me")
        wallet = data.get("wallet") or {}
        value = wallet.get("remaining_balance")
        return float(value) if isinstance(value, (int, float)) else None


register_avatar_provider("heygen", HeyGenAvatar.from_settings)
