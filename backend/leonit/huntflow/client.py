"""Клиент Huntflow API v2.

Сервис работает через протокол ``HuntflowClient``: реальная реализация ходит в
``https://api.huntflow.ru/v2`` по персональному токену (httpx, таймауты, один
повтор на 429/5xx, пагинация списков), фейковая держит фикстуры в памяти —
аккаунт, три вакансии, статусы воронки и соискателей — и запоминает созданных
соискателей и привязки, чтобы демо-режим вёл себя как настоящий.

Ошибки: ``HuntflowAuthError`` — токен отклонён (401), сервис переводит
подключение в ``error``; ``HuntflowUnavailableError`` — сеть, таймаут, 429/5xx
после повтора; ``HuntflowError`` — остальные ответы 4xx и невалидный JSON.
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from leonit.core.logging import get_logger

log = get_logger(__name__)

USER_AGENT = "LeonIT/0.1 (+huntflow-integration)"
PAGE_SIZE = 100
# Страховка от бесконечной пагинации, если API вернёт странный total_pages.
MAX_PAGES = 200


class HuntflowError(Exception):
    """Huntflow ответил ошибкой, которую повтор не исправит."""


class HuntflowAuthError(HuntflowError):
    """Токен отклонён: подключение нужно переоформить."""


class HuntflowUnavailableError(HuntflowError):
    """Сеть, таймаут или 429/5xx после повтора — задача очереди повторит позже."""


# --- данные ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HuntflowMe:
    id: int
    name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class HuntflowAccount:
    id: int
    name: str
    nick: str | None = None


@dataclass(frozen=True, slots=True)
class HuntflowVacancy:
    id: int
    position: str
    state: str | None = None
    company: str | None = None


@dataclass(frozen=True, slots=True)
class HuntflowStatus:
    id: int
    name: str
    type: str | None = None
    order: int = 0


@dataclass(frozen=True, slots=True)
class HuntflowApplicantLink:
    vacancy_id: int
    status_id: int | None


@dataclass(frozen=True, slots=True)
class HuntflowApplicantRecord:
    id: int
    first_name: str | None
    last_name: str | None
    middle_name: str | None
    email: str | None
    phone: str | None
    position: str | None
    links: tuple[HuntflowApplicantLink, ...] = ()

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(part.strip() for part in parts if part and part.strip())


@dataclass(frozen=True, slots=True)
class ApplicantCreate:
    first_name: str
    last_name: str
    middle_name: str | None = None
    email: str | None = None
    phone: str | None = None
    position: str | None = None

    def payload(self) -> dict[str, Any]:
        data = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "middle_name": self.middle_name,
            "email": self.email,
            "phone": self.phone,
            "position": self.position,
        }
        return {key: value for key, value in data.items() if value}


def split_full_name(full_name: str) -> tuple[str, str, str | None]:
    """«Фамилия Имя Отчество» → (first, last, middle); одно слово — это имя."""
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "", "", None
    if len(parts) == 1:
        return parts[0], "", None
    last, first, *rest = parts
    return first, last, " ".join(rest) or None


# --- протокол ----------------------------------------------------------------


class HuntflowClient(Protocol):
    async def me(self) -> HuntflowMe: ...

    async def accounts(self) -> list[HuntflowAccount]: ...

    async def vacancies(self, account_id: int) -> list[HuntflowVacancy]: ...

    async def statuses(self, account_id: int) -> list[HuntflowStatus]: ...

    async def applicants(
        self, account_id: int, *, vacancy_id: int | None = None
    ) -> list[HuntflowApplicantRecord]: ...

    async def get_applicant(
        self, account_id: int, applicant_id: int
    ) -> HuntflowApplicantRecord | None: ...

    async def create_applicant(
        self, account_id: int, data: ApplicantCreate
    ) -> HuntflowApplicantRecord: ...

    async def attach_vacancy(
        self,
        account_id: int,
        applicant_id: int,
        *,
        vacancy_id: int,
        status_id: int,
        comment: str,
    ) -> dict[str, Any]: ...

    async def applicant_logs(self, account_id: int, applicant_id: int) -> list[dict[str, Any]]: ...

    async def aclose(self) -> None: ...


# --- разбор ответов ----------------------------------------------------------


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_applicant(raw: dict[str, Any]) -> HuntflowApplicantRecord:
    links: list[HuntflowApplicantLink] = []
    for link in raw.get("links") or []:
        vacancy = link.get("vacancy") if isinstance(link, dict) else None
        vacancy_id = _int(vacancy.get("id") if isinstance(vacancy, dict) else vacancy)
        if vacancy_id is None:
            continue
        status = link.get("status")
        links.append(
            HuntflowApplicantLink(
                vacancy_id=vacancy_id,
                status_id=_int(status.get("id") if isinstance(status, dict) else status),
            )
        )
    return HuntflowApplicantRecord(
        id=int(raw["id"]),
        first_name=_str(raw.get("first_name")),
        last_name=_str(raw.get("last_name")),
        middle_name=_str(raw.get("middle_name")),
        email=(_str(raw.get("email")) or "").lower() or None,
        phone=_str(raw.get("phone")),
        position=_str(raw.get("position")),
        links=tuple(links),
    )


# --- реальный клиент ---------------------------------------------------------


class RealHuntflowClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delay_s: float = 1.0,
        page_size: int = PAGE_SIZE,
    ) -> None:
        self._timeout_s = timeout_s
        self._retry_delay_s = retry_delay_s
        self._page_size = page_size
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> RealHuntflowClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # --- транспорт -----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        last_error: str = ""
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(self._retry_delay_s)
            try:
                response = await self._http.request(method, path, params=params, json=json)
            except httpx.TimeoutException:
                last_error = f"Huntflow не ответил за {self._timeout_s:g} с"
                continue
            except httpx.HTTPError as exc:
                last_error = f"Huntflow недоступен: {type(exc).__name__}"
                continue
            if response.status_code == 401:
                raise HuntflowAuthError("Huntflow отклонил токен — переподключите интеграцию")
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"Huntflow ответил {response.status_code}"
                continue
            if response.status_code >= 400:
                raise HuntflowError(
                    f"Huntflow ответил {response.status_code}: {_error_detail(response)}"
                )
            if response.status_code == 204 or not response.content:
                return None
            try:
                return response.json()
            except ValueError as exc:
                raise HuntflowError("Huntflow вернул не JSON") from exc
        raise HuntflowUnavailableError(last_error or "Huntflow недоступен")

    async def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        items: list[Any] = []
        page = 1
        while page <= MAX_PAGES:
            data = await self._request(
                "GET", path, params={**(params or {}), "page": page, "count": self._page_size}
            )
            if not isinstance(data, dict):
                break
            chunk = data.get("items") or []
            items.extend(chunk)
            total_pages = _int(data.get("total_pages")) or 1
            if page >= total_pages or not chunk:
                break
            page += 1
        return items

    # --- методы --------------------------------------------------------------

    async def me(self) -> HuntflowMe:
        data = await self._request("GET", "/me")
        if not isinstance(data, dict) or "id" not in data:
            raise HuntflowError("Huntflow вернул неожиданный ответ на /me")
        return HuntflowMe(
            id=int(data["id"]), name=_str(data.get("name")), email=_str(data.get("email"))
        )

    async def accounts(self) -> list[HuntflowAccount]:
        data = await self._request("GET", "/accounts")
        items = data.get("items") if isinstance(data, dict) else None
        return [
            HuntflowAccount(
                id=int(item["id"]),
                name=str(item.get("name") or item["id"]),
                nick=_str(item.get("nick")),
            )
            for item in items or []
        ]

    async def vacancies(self, account_id: int) -> list[HuntflowVacancy]:
        items = await self._paginate(f"/accounts/{account_id}/vacancies")
        return [
            HuntflowVacancy(
                id=int(item["id"]),
                position=str(item.get("position") or f"Вакансия {item['id']}"),
                state=_str(item.get("state")),
                company=_str(item.get("company")),
            )
            for item in items
        ]

    async def statuses(self, account_id: int) -> list[HuntflowStatus]:
        data = await self._request("GET", f"/accounts/{account_id}/vacancies/statuses")
        items = data.get("items") if isinstance(data, dict) else None
        statuses = [
            HuntflowStatus(
                id=int(item["id"]),
                name=str(item.get("name") or item["id"]),
                type=_str(item.get("type")),
                order=_int(item.get("order")) or 0,
            )
            for item in items or []
            if not item.get("removed")
        ]
        return sorted(statuses, key=lambda s: (s.order, s.id))

    async def applicants(
        self, account_id: int, *, vacancy_id: int | None = None
    ) -> list[HuntflowApplicantRecord]:
        params = {"vacancy": vacancy_id} if vacancy_id is not None else {}
        items = await self._paginate(f"/accounts/{account_id}/applicants", params)
        return [parse_applicant(item) for item in items if isinstance(item, dict) and "id" in item]

    async def get_applicant(
        self, account_id: int, applicant_id: int
    ) -> HuntflowApplicantRecord | None:
        try:
            data = await self._request("GET", f"/accounts/{account_id}/applicants/{applicant_id}")
        except HuntflowError as exc:
            if isinstance(exc, HuntflowAuthError | HuntflowUnavailableError):
                raise
            return None
        return parse_applicant(data) if isinstance(data, dict) and "id" in data else None

    async def create_applicant(
        self, account_id: int, data: ApplicantCreate
    ) -> HuntflowApplicantRecord:
        raw = await self._request("POST", f"/accounts/{account_id}/applicants", json=data.payload())
        if not isinstance(raw, dict) or "id" not in raw:
            raise HuntflowError("Huntflow не вернул id созданного соискателя")
        return parse_applicant(raw)

    async def attach_vacancy(
        self,
        account_id: int,
        applicant_id: int,
        *,
        vacancy_id: int,
        status_id: int,
        comment: str,
    ) -> dict[str, Any]:
        raw = await self._request(
            "POST",
            f"/accounts/{account_id}/applicants/{applicant_id}/vacancy",
            json={"vacancy": vacancy_id, "status": status_id, "comment": comment},
        )
        return raw if isinstance(raw, dict) else {}

    async def applicant_logs(self, account_id: int, applicant_id: int) -> list[dict[str, Any]]:
        items = await self._paginate(f"/accounts/{account_id}/applicants/{applicant_id}/logs")
        return [item for item in items if isinstance(item, dict)]


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get("detail") or first.get("title") or first)[:200]
        return str(payload.get("detail") or payload.get("message") or payload)[:200]
    return str(payload)[:200]


# --- фейковый клиент ---------------------------------------------------------

FAKE_ME = HuntflowMe(id=1, name="Демо-рекрутер", email="demo@huntflow.local")
FAKE_ACCOUNT = HuntflowAccount(id=1, name="Napoleon IT (демо)", nick="napoleon-demo")
FAKE_VACANCIES: tuple[HuntflowVacancy, ...] = (
    HuntflowVacancy(id=101, position="Python-разработчик", state="OPEN", company="Napoleon IT"),
    HuntflowVacancy(
        id=102, position="Frontend-разработчик (React)", state="OPEN", company="Napoleon IT"
    ),
    HuntflowVacancy(id=103, position="Аналитик данных", state="HOLD", company="Napoleon IT"),
)
FAKE_STATUSES: tuple[HuntflowStatus, ...] = (
    HuntflowStatus(id=1, name="Новый", type="user", order=1),
    HuntflowStatus(id=2, name="Скрининг", type="user", order=2),
    HuntflowStatus(id=3, name="Видеоинтервью LeonIT", type="user", order=3),
    HuntflowStatus(id=4, name="Техническое интервью", type="user", order=4),
    HuntflowStatus(id=5, name="Оффер", type="offer", order=5),
    HuntflowStatus(id=6, name="Отказ", type="trash", order=6),
)
_FAKE_APPLICANTS: tuple[dict[str, Any], ...] = (
    {
        "id": 1001,
        "first_name": "Мария",
        "last_name": "Смирнова",
        "email": "maria.smirnova@example.com",
        "phone": "+7 900 000-00-01",
        "position": "Python-разработчик",
        "links": [{"vacancy": 101, "status": 1}],
    },
    {
        "id": 1002,
        "first_name": "Алексей",
        "last_name": "Кузнецов",
        "middle_name": "Игоревич",
        "email": "a.kuznetsov@example.com",
        "position": "Python-разработчик",
        "links": [{"vacancy": 101, "status": 2}],
    },
    {
        # Без e-mail: при импорте такой соискатель пропускается.
        "id": 1003,
        "first_name": "Дарья",
        "last_name": "Попова",
        "phone": "+7 900 000-00-03",
        "position": "Python-разработчик",
        "links": [{"vacancy": 101, "status": 1}],
    },
    {
        "id": 1004,
        "first_name": "Илья",
        "last_name": "Морозов",
        "email": "ilya.morozov@example.com",
        "position": "Frontend-разработчик",
        "links": [{"vacancy": 102, "status": 1}],
    },
    {
        "id": 1005,
        "first_name": "Елена",
        "last_name": "Волкова",
        "email": "elena.volkova@example.com",
        "phone": "+7 900 000-00-05",
        "position": "Аналитик данных",
        "links": [{"vacancy": 103, "status": 2}],
    },
)


@dataclass(slots=True)
class FakeHuntflowStore:
    """Состояние демо-аккаунта: соискатели, их привязки и журнал."""

    applicants: dict[int, dict[str, Any]] = field(default_factory=dict)
    logs: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    next_applicant_id: int = 2001
    next_log_id: int = 1

    @classmethod
    def seeded(cls) -> FakeHuntflowStore:
        store = cls()
        for raw in _FAKE_APPLICANTS:
            store.applicants[raw["id"]] = copy.deepcopy(raw)
        return store


_STORES: dict[str, FakeHuntflowStore] = {}


def reset_fake_stores() -> None:
    """Сбросить состояние демо-аккаунтов (тесты)."""
    _STORES.clear()


def fake_store(key: str) -> FakeHuntflowStore:
    store = _STORES.get(key)
    if store is None:
        store = _STORES[key] = FakeHuntflowStore.seeded()
    return store


class FakeHuntflowClient:
    """Фикстуры вместо сети; состояние живёт в процессе и делится по ключу организации."""

    def __init__(self, key: str = "default") -> None:
        self._store = fake_store(key)

    async def aclose(self) -> None:
        return None

    async def __aenter__(self) -> FakeHuntflowClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def me(self) -> HuntflowMe:
        return FAKE_ME

    async def accounts(self) -> list[HuntflowAccount]:
        return [FAKE_ACCOUNT]

    async def vacancies(self, account_id: int) -> list[HuntflowVacancy]:
        self._check_account(account_id)
        return list(FAKE_VACANCIES)

    async def statuses(self, account_id: int) -> list[HuntflowStatus]:
        self._check_account(account_id)
        return list(FAKE_STATUSES)

    async def applicants(
        self, account_id: int, *, vacancy_id: int | None = None
    ) -> list[HuntflowApplicantRecord]:
        self._check_account(account_id)
        records = [parse_applicant(raw) for raw in self._store.applicants.values()]
        if vacancy_id is not None:
            records = [r for r in records if any(link.vacancy_id == vacancy_id for link in r.links)]
        return records

    async def get_applicant(
        self, account_id: int, applicant_id: int
    ) -> HuntflowApplicantRecord | None:
        self._check_account(account_id)
        raw = self._store.applicants.get(applicant_id)
        return parse_applicant(raw) if raw else None

    async def create_applicant(
        self, account_id: int, data: ApplicantCreate
    ) -> HuntflowApplicantRecord:
        self._check_account(account_id)
        applicant_id = self._store.next_applicant_id
        self._store.next_applicant_id += 1
        raw = {"id": applicant_id, **data.payload(), "links": []}
        self._store.applicants[applicant_id] = raw
        return parse_applicant(raw)

    async def attach_vacancy(
        self,
        account_id: int,
        applicant_id: int,
        *,
        vacancy_id: int,
        status_id: int,
        comment: str,
    ) -> dict[str, Any]:
        self._check_account(account_id)
        raw = self._store.applicants.get(applicant_id)
        if raw is None:
            raise HuntflowError("Huntflow ответил 404: соискатель не найден")
        if not any(v.id == vacancy_id for v in FAKE_VACANCIES):
            raise HuntflowError("Huntflow ответил 404: вакансия не найдена")
        if not any(s.id == status_id for s in FAKE_STATUSES):
            raise HuntflowError("Huntflow ответил 400: неизвестный статус")
        links = [link for link in raw.get("links") or [] if link.get("vacancy") != vacancy_id]
        links.append({"vacancy": vacancy_id, "status": status_id})
        raw["links"] = links
        entry = {
            "id": self._store.next_log_id,
            "type": "STATUS",
            "vacancy": vacancy_id,
            "status": status_id,
            "comment": comment,
        }
        self._store.next_log_id += 1
        self._store.logs.setdefault(applicant_id, []).append(entry)
        return dict(entry)

    async def applicant_logs(self, account_id: int, applicant_id: int) -> list[dict[str, Any]]:
        self._check_account(account_id)
        return [dict(entry) for entry in self._store.logs.get(applicant_id, [])]

    @staticmethod
    def _check_account(account_id: int) -> None:
        if account_id != FAKE_ACCOUNT.id:
            raise HuntflowError("Huntflow ответил 404: аккаунт не найден")
