from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

HhModeLiteral = Literal["fake", "real"]
ConnectionStatusLiteral = Literal["connected", "error", "disconnected"]
DialogStateLiteral = Literal[
    "new",
    "greeting_sent",
    "awaiting_slot",
    "link_sent",
    "done",
    "declined",
    "needs_recruiter",
]


class HhConnectionOut(BaseModel):
    id: str
    mode: HhModeLiteral
    status: ConnectionStatusLiteral
    employer_id: str
    employer_name: str
    last_error: str
    connected_at: datetime
    last_synced_at: datetime | None
    # Полный адрес вебхука виден только владельцу.
    webhook_url: str | None
    # Токен, подключённый без refresh_token (импорт из другого приложения), не
    # обновляется сам: интерфейс показывает срок и просит вставить новый.
    token_refreshable: bool = True
    expires_at: datetime | None = None


class HhTokenConnectIn(BaseModel):
    """Подключение готовым токеном, выданным hh.ru другому приложению того же работодателя.

    Без refresh_token сервис никогда не обновляет пару и не инвалидирует токен у
    приложения-источника; после истечения срока токен нужно вставить заново.
    """

    access_token: str = Field(min_length=16, max_length=4096)
    refresh_token: str | None = Field(default=None, max_length=4096)
    expires_at: datetime | None = None


class HhStatusOut(BaseModel):
    mode: HhModeLiteral
    configured: bool
    sync_interval_minutes: int
    connection: HhConnectionOut | None


class OAuthStartOut(BaseModel):
    url: str


class DialogSettings(BaseModel):
    enabled: bool = True
    max_days: int = Field(default=7, ge=1, le=60)
    greeting: str = Field(min_length=1, max_length=2000)
    clarify: str = Field(min_length=1, max_length=2000)
    link: str = Field(min_length=1, max_length=2000)


class DialogOut(DialogSettings):
    placeholders: list[str]
    preview: dict[str, str]


class VacancyLinkOut(BaseModel):
    id: str
    hh_vacancy_id: str
    hh_title: str
    hh_url: str
    vacancy_id: str
    vacancy_title: str
    vacancy_status: str
    dialog_enabled: bool
    max_days: int
    negotiation_count: int
    created_at: datetime


class HhVacancyOut(BaseModel):
    id: str
    name: str
    url: str
    area: str
    salary: str
    published_at: datetime | None
    key_skills: list[str]
    link: VacancyLinkOut | None


class LinkVacancyIn(BaseModel):
    vacancy_id: str


class DialogMessageOut(BaseModel):
    role: Literal["bot", "candidate", "recruiter"]
    text: str
    at: datetime | None
    hh_message_id: str | None
    step: str | None = None


class NegotiationOut(BaseModel):
    id: str
    negotiation_id: str
    state: DialogStateLiteral
    chosen_date: date | None
    candidate_id: str
    candidate_name: str
    candidate_email: str
    vacancy_id: str
    vacancy_title: str
    vacancy_link_id: str
    hh_vacancy_id: str
    interview_id: str | None
    interview_status: str | None
    messages: list[DialogMessageOut]
    last_error: str
    last_synced_at: datetime | None
    created_at: datetime


class TakeOverIn(BaseModel):
    # Срок действия ссылки в днях; None — по настройке вакансии.
    days: int | None = Field(default=None, ge=1, le=60)


class SyncQueuedOut(BaseModel):
    job_id: str
    queued: bool


def dialog_preview(values: dict[str, Any], settings: DialogSettings) -> dict[str, str]:
    from leonit.hh.dialog import render

    return {
        "greeting": render(settings.greeting, values),
        "clarify": render(settings.clarify, values),
        "link": render(settings.link, values),
    }
