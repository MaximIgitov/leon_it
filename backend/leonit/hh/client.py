"""Клиент employer API hh.ru.

``HhClient`` — протокол, который видит предметный код; ``RealHhClient`` ходит в
API по HTTP (таймауты, обновление токена при истечении и 401, один повтор на
429/5xx с уважением к ``Retry-After``, идемпотентная отправка сообщений), а
``leonit.hh.fake.FakeHhClient`` отдаёт то же самое из фикстур без сети.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from leonit.core.config import Settings
from leonit.core.errors import UpstreamError
from leonit.core.time import aware, utcnow
from leonit.hh.types import (
    HhEmployer,
    HhMessage,
    HhNegotiationInfo,
    HhResume,
    HhTokens,
    HhVacancy,
    salary_text,
)

DEFAULT_TIMEOUT_S = 20.0
DEFAULT_TOKEN_TTL_S = 14 * 24 * 3600
_MAX_RETRY_AFTER_S = 5.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Ошибки oauth, после которых переподключение обязательно: обновлять токен бесполезно.
_REVOKED_VALUES = frozenset(
    {
        "token_revoked",
        "token_was_revoked",
        "token_deactivated",
        "bad_token",
        "bad_authorization",
        "application_not_found",
        "token_has_already_been_refreshed",
    }
)


class HhError(UpstreamError):
    """HH недоступен или ответил ошибкой."""


class HhAuthError(HhError):
    """Авторизация HH недействительна: нужно переподключить аккаунт."""


class HhClient(Protocol):
    async def me(self) -> HhEmployer: ...

    async def employer_vacancies(self, employer_id: str) -> list[HhVacancy]: ...

    async def vacancy(self, vacancy_id: str) -> HhVacancy: ...

    async def negotiations(self, vacancy_id: str) -> list[HhNegotiationInfo]: ...

    async def resume(self, resume_id: str, *, negotiation_id: str | None = None) -> HhResume: ...

    async def messages(
        self, chat_id: str, *, after_message_id: str | None = None
    ) -> list[HhMessage]: ...

    async def send_message(
        self, chat_id: str, text: str, *, idempotency_key: str
    ) -> HhMessage | None: ...


TokensCallback = Callable[[HhTokens], Awaitable[None]]


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _error_entries(response: httpx.Response) -> list[dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("errors")
    if isinstance(entries, list):
        return [item for item in entries if isinstance(item, dict)]
    if payload.get("error"):
        return [{"type": payload.get("error"), "value": payload.get("error_description")}]
    return []


def _error_values(response: httpx.Response, error_type: str) -> set[str]:
    return {
        str(item.get("value") or "").strip().replace("-", "_").replace(" ", "_").lower()
        for item in _error_entries(response)
        if str(item.get("type") or "").lower() == error_type
    }


def error_summary(response: httpx.Response) -> str:
    parts: list[str] = []
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        description = str(payload.get("description") or payload.get("error_description") or "")
        if description.strip():
            parts.append(description.strip())
        for item in _error_entries(response):
            label = "/".join(
                str(item.get(key) or "").strip()
                for key in ("type", "value", "reason")
                if item.get(key)
            )
            if label and label not in parts:
                parts.append(label)
        if payload.get("request_id"):
            parts.append(f"request_id={payload['request_id']}")
    summary = "; ".join(parts) or (response.text or "")[:200]
    return f"HTTP {response.status_code}: {summary}"[:500]


def tokens_from_payload(data: dict[str, Any]) -> HhTokens:
    try:
        access = str(data["access_token"])
    except KeyError as error:
        raise HhError("HH не вернул access_token") from error
    ttl = int(data.get("expires_in") or DEFAULT_TOKEN_TTL_S)
    return HhTokens(
        access_token=access,
        refresh_token=str(data.get("refresh_token") or ""),
        expires_at=utcnow() + timedelta(seconds=ttl),
    )


def parse_vacancy(data: dict[str, Any]) -> HhVacancy:
    return HhVacancy(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        url=str(data.get("alternate_url") or ""),
        description_html=str(data.get("description") or ""),
        key_skills=[
            str(item.get("name") or "")
            for item in data.get("key_skills") or []
            if isinstance(item, dict) and item.get("name")
        ],
        area=str((data.get("area") or {}).get("name") or ""),
        salary=salary_text(data.get("salary")),
        published_at=_parse_datetime(data.get("published_at")),
    )


def parse_resume(data: dict[str, Any]) -> HhResume:
    email: str | None = None
    phone: str | None = None
    for contact in data.get("contact") or []:
        if not isinstance(contact, dict):
            continue
        kind = str((contact.get("type") or {}).get("id") or "")
        value = contact.get("value")
        if isinstance(value, dict):
            value = value.get("formatted")
        if not value:
            continue
        if kind == "email" and email is None:
            email = str(value).strip().lower()
        elif kind in ("cell", "phone", "work") and phone is None:
            phone = str(value).strip()
    experience = []
    for item in data.get("experience") or []:
        if isinstance(item, dict):
            experience.append(
                {
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "company": item.get("company"),
                    "position": item.get("position"),
                    "description": item.get("description"),
                }
            )
    skills = data.get("skill_set") or []
    return HhResume(
        id=str(data.get("id") or ""),
        first_name=str(data.get("first_name") or ""),
        last_name=str(data.get("last_name") or ""),
        middle_name=str(data.get("middle_name") or ""),
        email=email,
        phone=phone,
        title=str(data.get("title") or ""),
        experience=experience,
        skills=[str(skill) for skill in skills if skill],
        url=str(data.get("alternate_url") or ""),
    )


def parse_negotiation(data: dict[str, Any]) -> HhNegotiationInfo:
    resume = data.get("resume") or {}
    return HhNegotiationInfo(
        id=str(data.get("id") or ""),
        vacancy_id=str((data.get("vacancy") or {}).get("id") or ""),
        resume_id=str(resume.get("id") or ""),
        chat_id=str(data.get("chat_id") or ""),
        created_at=_parse_datetime(data.get("created_at")),
        state=str((data.get("state") or {}).get("id") or "response").lower(),
    )


def parse_message(data: dict[str, Any]) -> HhMessage:
    """Сообщение чата в любом из двух форматов hh.

    ``/negotiations/{id}/messages`` и ответ на отправку отдают ``author.participant_type``,
    ``text`` и ``created_at``; ``/common/chats/{chat_id}/messages`` — ``sender_display_info.role``,
    ``payload.text`` и ``creation_time``.
    """
    author = data.get("author") or {}
    sender = data.get("sender_display_info") or {}
    payload = data.get("payload") or {}
    participant = author.get("participant_type") or sender.get("role") or "employer"
    text = data.get("text")
    if text is None:
        text = payload.get("text")
    return HhMessage(
        id=str(data.get("id") or ""),
        author=str(participant).lower(),
        text=str(text or ""),
        created_at=_parse_datetime(data.get("created_at") or data.get("creation_time")),
    )


def _headers(settings: Settings, token: str | None = None) -> dict[str, str]:
    headers = {"HH-User-Agent": settings.HH_USER_AGENT, "User-Agent": settings.HH_USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class HhOAuth:
    """Шаги OAuth, которым не нужен токен: ссылка авторизации, обмен кода, refresh."""

    def __init__(self, settings: Settings, *, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._http = http

    def authorize_url(self, *, state: str, code_challenge: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.HH_CLIENT_ID or "",
                "state": state,
                "redirect_uri": self.settings.hh_redirect_url,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.settings.HH_OAUTH_BASE.rstrip('/')}/oauth/authorize?{query}"

    async def _token_request(self, data: dict[str, str]) -> HhTokens:
        url = f"{self.settings.HH_API_BASE.rstrip('/')}/token"
        try:
            if self._http is not None:
                response = await self._http.post(url, data=data, headers=_headers(self.settings))
            else:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S) as http:
                    response = await http.post(url, data=data, headers=_headers(self.settings))
        except httpx.HTTPError as error:
            raise HhError(f"HH недоступен: {error.__class__.__name__}") from error
        if response.status_code in (400, 401, 403):
            raise HhAuthError(f"HH отклонил авторизацию ({error_summary(response)})")
        if response.is_error:
            raise HhError(f"Ошибка HH при получении токена ({error_summary(response)})")
        return tokens_from_payload(response.json())

    async def exchange_code(self, code: str, *, code_verifier: str) -> HhTokens:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": self.settings.HH_CLIENT_ID or "",
                "client_secret": self.settings.HH_CLIENT_SECRET or "",
                "redirect_uri": self.settings.hh_redirect_url,
                "code": code,
                "code_verifier": code_verifier,
            }
        )

    async def refresh(self, refresh_token: str) -> HhTokens:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )


class RealHhClient:
    """Запросы к api.hh.ru от имени подключения.

    Токены передаются снаружи; после обновления вызывается ``on_tokens`` —
    сервис сохраняет их в базе в зашифрованном виде. HH выдаёт одноразовый
    refresh_token, поэтому обновление идёт под asyncio-замком и только по
    истечении срока (или по 401).
    """

    def __init__(
        self,
        settings: Settings,
        tokens: HhTokens,
        *,
        on_tokens: TokensCallback | None = None,
        manager_account_id: str | None = None,
        http: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self.on_tokens = on_tokens
        self.manager_account_id = manager_account_id
        self._http = http
        self._own_http = http is None
        self._sleep = sleep
        self._timeout_s = timeout_s
        self._oauth = HhOAuth(settings, http=http)
        self._refresh_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> RealHhClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout_s)
            self._oauth = HhOAuth(self.settings, http=self._http)
        return self._http

    # --- токены -------------------------------------------------------------

    async def _access_token(self, *, rejected: str | None = None) -> str:
        expires_at = aware(self.tokens.expires_at)
        if rejected is None and expires_at is not None and expires_at > utcnow():
            return self.tokens.access_token
        async with self._refresh_lock:
            if rejected is not None and self.tokens.access_token != rejected:
                return self.tokens.access_token
            if not self.tokens.refresh_token:
                raise HhAuthError("Срок токена HH истёк, а refresh_token отсутствует")
            fresh = await self._oauth.refresh(self.tokens.refresh_token)
            if not fresh.refresh_token:
                fresh.refresh_token = self.tokens.refresh_token
            self.tokens = fresh
            if self.on_tokens is not None:
                await self.on_tokens(fresh)
            return fresh.access_token

    # --- запросы ------------------------------------------------------------

    async def _send(
        self, method: str, path: str, *, token: str, params: dict | None, json: dict | None
    ) -> httpx.Response:
        headers = _headers(self.settings, token)
        if self.manager_account_id:
            headers["X-Manager-Account-Id"] = self.manager_account_id
        url = f"{self.settings.HH_API_BASE.rstrip('/')}{path}"
        try:
            return await self.http.request(method, url, params=params, json=json, headers=headers)
        except httpx.HTTPError as error:
            raise HhError(f"HH недоступен: {error.__class__.__name__}") from error

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        token = await self._access_token()
        response = await self._send(method, path, token=token, params=params, json=json)
        if response.status_code in (401, 403):
            values = _error_values(response, "oauth")
            if values & _REVOKED_VALUES:
                raise HhAuthError(f"Авторизация HH отозвана ({error_summary(response)})")
            if response.status_code == 401 or "token_expired" in values:
                token = await self._access_token(rejected=token)
                response = await self._send(method, path, token=token, params=params, json=json)
        # 429 и кратковременные 5xx: один повтор безопасен для GET и для POST
        # с idempotency_key — второй такой же запрос HH не выполнит дважды.
        idempotent = method.upper() != "POST" or bool(json and json.get("idempotency_key"))
        if response.status_code in _RETRY_STATUSES and idempotent:
            await self._sleep(_retry_after_s(response))
            response = await self._send(method, path, token=token, params=params, json=json)
        if response.status_code in (401, 403):
            raise HhAuthError(f"Авторизация HH недействительна ({error_summary(response)})")
        if response.is_error:
            raise HhError(f"Ошибка HH ({error_summary(response)})")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise HhError("HH вернул не JSON") from error

    async def _paged(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 0
        while True:
            data = await self.request("GET", path, params={**params, "page": page, "per_page": 50})
            if not isinstance(data, dict):
                break
            items.extend(item for item in data.get("items") or [] if isinstance(item, dict))
            if page + 1 >= int(data.get("pages") or 1):
                break
            page += 1
        return items

    # --- HhClient -------------------------------------------------------------

    async def me(self) -> HhEmployer:
        data = await self.request("GET", "/me")
        employer = (data or {}).get("employer") or {}
        manager = (data or {}).get("manager") or {}
        employer_id = str(employer.get("id") or "")
        # Заголовок X-Manager-Account-Id ждёт идентификатор аккаунта из
        # /manager_accounts/mine, а не manager.id из /me: с последним hh отвечает
        # 403 manager_extra_account_not_found. Берём аккаунт этого работодателя,
        # без ответа списка — оставляем manager.id как раньше.
        account_id: str | None = str(manager["id"]) if manager.get("id") else None
        if employer_id:
            try:
                mine = await self.request("GET", "/manager_accounts/mine")
            except HhError:
                mine = None
            items = (mine or {}).get("items") if isinstance(mine, dict) else None
            for item in items or []:
                account_employer = (item or {}).get("employer") or {}
                if str(account_employer.get("id") or "") == employer_id and item.get("id"):
                    account_id = str(item["id"])
                    break
        return HhEmployer(
            id=employer_id,
            name=str(employer.get("name") or ""),
            user_id=str((data or {}).get("id") or ""),
            manager_account_id=account_id,
        )

    async def employer_vacancies(self, employer_id: str) -> list[HhVacancy]:
        items = await self._paged(
            f"/employers/{employer_id}/vacancies/active", {"all_accessible": "true"}
        )
        return [parse_vacancy(item) for item in items]

    async def vacancy(self, vacancy_id: str) -> HhVacancy:
        return parse_vacancy(await self.request("GET", f"/vacancies/{vacancy_id}") or {})

    async def negotiations(self, vacancy_id: str) -> list[HhNegotiationInfo]:
        # Коллекция response — только входящие отклики; приглашениям работодателя
        # автоматическое приветствие писать нельзя.
        items = await self._paged("/negotiations/response", {"vacancy_id": vacancy_id})
        return [parse_negotiation(item) for item in items]

    async def resume(self, resume_id: str, *, negotiation_id: str | None = None) -> HhResume:
        params = {"topic_id": negotiation_id} if negotiation_id else None
        return parse_resume(await self.request("GET", f"/resumes/{resume_id}", params=params))

    async def messages(
        self, chat_id: str, *, after_message_id: str | None = None
    ) -> list[HhMessage]:
        params: dict[str, Any] = {"order": "next", "limit": 50}
        if after_message_id:
            params["start_message_id"] = after_message_id
        data = await self.request("GET", f"/common/chats/{chat_id}/messages", params=params)
        # Чаты отдают список в ``messages``; ``items`` — на случай старого формата.
        raw = (data or {}).get("messages")
        if raw is None:
            raw = (data or {}).get("items") or []
        items = [parse_message(item) for item in raw]
        # start_message_id включает саму стартовую точку — её мы уже видели.
        return [item for item in items if item.id != after_message_id]

    async def send_message(
        self, chat_id: str, text: str, *, idempotency_key: str
    ) -> HhMessage | None:
        payload = {"idempotency_key": idempotency_key, "text": text, "is_automated": True}
        try:
            data = await self.request("POST", f"/common/chats/{chat_id}/messages", json=payload)
        except HhError as error:
            # 409 — ключ уже принят: сообщение ушло раньше, повтор не нужен.
            if "HTTP 409" in str(error):
                return None
            raise
        if not isinstance(data, dict) or not data.get("id"):
            return None
        return parse_message(data)


def _retry_after_s(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After", "1")
    try:
        return max(0.0, min(float(raw), _MAX_RETRY_AFTER_S))
    except ValueError:
        return 1.0
