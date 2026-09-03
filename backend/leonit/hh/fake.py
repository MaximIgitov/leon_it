"""Фейковый клиент HH на фикстурах — для CI, тестов и демо без ключей.

Отдаёт работодателя, вакансии и отклики из ``fixtures/*.json``. Ответы
кандидатов заданы сценарием (``replies`` у отклика): k-я реплика появляется
после k-го сообщения бота. Номера зашиты в идентификаторы сообщений
(``<chat>-b<k>`` у бота, ``<chat>-c<k>`` у кандидата), поэтому клиент не
хранит состояние: по ``after_message_id`` он восстанавливает, где диалог, — и
тот же сценарий воспроизводится в другом процессе и после рестарта воркера.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from leonit.core.errors import NotFoundError
from leonit.core.time import utcnow
from leonit.hh.client import parse_negotiation, parse_resume, parse_vacancy
from leonit.hh.types import (
    HhEmployer,
    HhMessage,
    HhNegotiationInfo,
    HhResume,
    HhVacancy,
)

FIXTURES_DIR = Path(__file__).with_name("fixtures")
_MESSAGE_ID_RE = re.compile(r"^(?P<chat>.+)-(?P<kind>[bc])(?P<n>\d+)$")


@lru_cache
def _load(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _parse_message_id(message_id: str | None) -> tuple[str, int] | None:
    match = _MESSAGE_ID_RE.match(message_id or "")
    if not match:
        return None
    return match.group("kind"), int(match.group("n"))


class FakeHhClient:
    def __init__(self) -> None:
        self._bot_counts: dict[str, int] = {}
        # Что «отправил» бот — для тестов и отладки.
        self.sent: list[tuple[str, str, str]] = []

    # --- справочники --------------------------------------------------------

    @staticmethod
    def _negotiation_rows() -> list[dict[str, Any]]:
        return list(_load("negotiations.json"))

    async def me(self) -> HhEmployer:
        data = _load("employer.json")
        return HhEmployer(
            id=str(data["id"]),
            name=str(data["name"]),
            user_id=str(data.get("user_id") or ""),
            manager_account_id=data.get("manager_account_id"),
        )

    async def employer_vacancies(self, employer_id: str) -> list[HhVacancy]:
        return [parse_vacancy(item) for item in _load("vacancies.json")]

    async def vacancy(self, vacancy_id: str) -> HhVacancy:
        for item in _load("vacancies.json"):
            if str(item["id"]) == vacancy_id:
                return parse_vacancy(item)
        raise NotFoundError("Вакансия HH не найдена")

    async def negotiations(self, vacancy_id: str) -> list[HhNegotiationInfo]:
        return [
            parse_negotiation(item)
            for item in self._negotiation_rows()
            if str(item["vacancy"]["id"]) == vacancy_id
        ]

    async def resume(self, resume_id: str, *, negotiation_id: str | None = None) -> HhResume:
        for item in self._negotiation_rows():
            if str(item["resume"]["id"]) == resume_id:
                return parse_resume(item["resume"])
        raise NotFoundError("Резюме HH не найдено")

    # --- чат ----------------------------------------------------------------

    def _replies(self, chat_id: str) -> list[str]:
        for item in self._negotiation_rows():
            if str(item["chat_id"]) == chat_id:
                return [str(text) for text in item.get("replies") or []]
        return []

    async def messages(
        self, chat_id: str, *, after_message_id: str | None = None
    ) -> list[HhMessage]:
        parsed = _parse_message_id(after_message_id)
        seen_replies = 0
        if parsed is not None:
            kind, n = parsed
            self._bot_counts[chat_id] = max(self._bot_counts.get(chat_id, 0), n)
            seen_replies = n if kind == "c" else n - 1
        bot_count = self._bot_counts.get(chat_id, 0)
        replies = self._replies(chat_id)
        now = utcnow()
        return [
            HhMessage(id=f"{chat_id}-c{k}", author="applicant", text=replies[k - 1], created_at=now)
            for k in range(seen_replies + 1, bot_count + 1)
            if k <= len(replies)
        ]

    async def send_message(
        self, chat_id: str, text: str, *, idempotency_key: str
    ) -> HhMessage | None:
        n = self._bot_counts.get(chat_id, 0) + 1
        self._bot_counts[chat_id] = n
        self.sent.append((chat_id, text, idempotency_key))
        return HhMessage(id=f"{chat_id}-b{n}", author="employer", text=text, created_at=utcnow())
