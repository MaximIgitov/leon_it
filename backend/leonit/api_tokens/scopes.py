"""Области доступа публичного API и их соответствие действиям ``authorize``.

Ручки ``/api/v1`` проверяют область токена на входе (``require_scope``), а
сервисы внутри — действия через ``authorize``. Таблица ниже связывает одно с
другим: токен получает ровно те действия, которые нужны его областям, и ничего
«в нагрузку» от ближайшей роли. Область не может быть шире прав того, кто
создаёт токен: при создании каждое действие области проверяется на создателе.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable

TOKEN_PREFIX = "leonit_"
# Сколько символов токена показывать в списке («leonit_AbCdE»): по ним владелец
# отличает токены, а подобрать остаток по ним нельзя.
TOKEN_DISPLAY_LENGTH = 12

# Область → действия authorize. Запись подразумевает чтение того же ресурса;
# приглашение на интервью возвращает интервью, поэтому candidates:write включает
# interview.read; отчёт строится поверх интервью — reports:read тоже.
# media:read действий не добавляет: сам отчёт открывает reports:read (ручка
# проверяет именно её), а media:read лишь разрешает выдавать в нём подписанные
# ссылки на медиа. Токен с одной media:read не откроет ничего.
SCOPE_ACTIONS: dict[str, frozenset[str]] = {
    "vacancies:read": frozenset({"vacancy.read"}),
    "vacancies:write": frozenset({"vacancy.read", "vacancy.write"}),
    "candidates:read": frozenset({"candidate.read"}),
    "candidates:write": frozenset({"candidate.read", "candidate.write", "interview.read"}),
    "interviews:read": frozenset({"interview.read"}),
    "reports:read": frozenset({"interview.read", "report.read"}),
    "media:read": frozenset(),
}

SCOPES: tuple[str, ...] = tuple(SCOPE_ACTIONS)

SCOPE_DESCRIPTIONS: dict[str, str] = {
    "vacancies:read": "Список и карточки вакансий, включая вопросы и рубрику.",
    "vacancies:write": "Создание черновиков вакансий.",
    "candidates:read": "Список кандидатов организации.",
    "candidates:write": "Создание кандидатов и приглашение на интервью (ссылка выдаётся в ответе).",
    "interviews:read": "Статусы, таймстемпы и решения по интервью.",
    "reports:read": "Заключение модели, транскрипты ответов и ранжирование по вакансии.",
    "media:read": "Подписанные короткоживущие ссылки на видео и аудио ответов в отчёте.",
}


def actions_for(scopes: Iterable[str]) -> frozenset[str]:
    """Действия ``authorize``, доступные токену с этими областями."""
    actions: set[str] = set()
    for scope in scopes:
        actions |= SCOPE_ACTIONS.get(scope, frozenset())
    return frozenset(actions)


def generate_api_token() -> str:
    """``leonit_`` + 256 бит случайности в URL-безопасном алфавите."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def display_prefix(token: str) -> str:
    return token[:TOKEN_DISPLAY_LENGTH]
