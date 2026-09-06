"""Протокол провайдера аватара и заглушка по умолчанию."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class AvatarClip:
    """Готовый клип с произнесённым вопросом.

    ``url`` — адрес, который откроет браузер кандидата: либо ссылка провайдера,
    либо подписанная ссылка на файл в нашем хранилище (тогда провайдер кладёт
    файл в ``Storage`` и заполняет ``storage_key`` — комната переподпишет
    ссылку, а кэш не протухнет вместе с подписью).
    """

    url: str
    duration_s: float | None = None
    storage_key: str | None = None


@runtime_checkable
class AvatarProvider(Protocol):
    """Рендер клипа с вопросом.

    Реализация обязана быть асинхронной и ходить наружу только через
    ``httpx.AsyncClient`` с таймаутами. ``None`` в ответе означает «клипа нет»
    (провайдер не смог, лимит исчерпан) — комната покажет персону без видео,
    интервью не останавливается. Ошибки сети/провайдера можно бросать: комната
    ловит их, пишет в лог и тоже показывает персону.
    """

    name: str
    # Необязательный атрибут ``variant`` — облик и кадр (аватар, движок, формат):
    # входит в ключ кэша, чтобы переключение аватара не отдавало старые клипы.
    # False у заглушки: комната сообщает клиенту enabled=false, даже если флаг включён.
    enabled: bool
    # True — рендер занимает минуты: комната не ждёт, а ставит задачу прогрева
    # (``leonit.avatar.jobs``) и отдаёт только готовые клипы из кэша.
    background_render: bool

    async def render(
        self, question_text: str, voice: str | None, language: str
    ) -> AvatarClip | None: ...


class NullAvatarProvider:
    """Провайдер по умолчанию: аватара нет, комната показывает персону LeonIT."""

    name = "none"
    enabled = False
    background_render = False

    async def render(
        self, question_text: str, voice: str | None, language: str
    ) -> AvatarClip | None:
        return None
