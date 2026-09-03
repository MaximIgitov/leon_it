from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ModeLiteral = Literal["real", "fake"]
ConnectionStatusLiteral = Literal["active", "needs_account", "error"]
PushStatusLiteral = Literal["not_pushed", "linked", "queued", "pushing", "pushed", "error"]


class HuntflowAccountOut(BaseModel):
    id: int
    name: str
    nick: str | None = None


class ConnectionOut(BaseModel):
    connected: bool
    mode: ModeLiteral | None = None
    status: ConnectionStatusLiteral | None = None
    account: HuntflowAccountOut | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    last_error: str | None = None
    last_checked_at: datetime | None = None
    connected_at: datetime | None = None
    connected_by_email: str | None = None
    # Заполняется, когда у токена несколько аккаунтов и нужно выбрать один.
    available_accounts: list[HuntflowAccountOut] = Field(default_factory=list)
    linked_vacancies: int = 0
    # Кнопка «Подключить демо» доступна, если HUNTFLOW_MODE не real.
    demo_available: bool
    can_manage: bool


class ConnectIn(BaseModel):
    token: str | None = Field(default=None, max_length=4096)
    demo: bool = False
    account_id: int | None = None

    @model_validator(mode="after")
    def _token_or_demo(self) -> ConnectIn:
        self.token = (self.token or "").strip() or None
        if not self.demo and not self.token:
            raise ValueError("Укажите персональный токен Huntflow или подключите демо")
        return self


class SelectAccountIn(BaseModel):
    account_id: int


class HuntflowStatusOut(BaseModel):
    id: int
    name: str
    type: str | None = None
    order: int = 0


class VacancyLinkOut(BaseModel):
    vacancy_id: str
    vacancy_title: str
    vacancy_status: str
    huntflow_vacancy_id: int
    huntflow_vacancy_title: str
    status_id: int | None
    status_name: str | None
    last_imported_at: datetime | None
    created_at: datetime


class HuntflowVacancyOut(BaseModel):
    id: int
    position: str
    state: str | None = None
    company: str | None = None
    links: list[VacancyLinkOut] = Field(default_factory=list)


class HuntflowVacanciesOut(BaseModel):
    items: list[HuntflowVacancyOut]
    statuses: list[HuntflowStatusOut]


class LinkIn(BaseModel):
    huntflow_vacancy_id: int
    status_id: int | None = None


class ImportResult(BaseModel):
    total: int
    created: int
    existing: int
    skipped: int


class PushIn(BaseModel):
    interview_id: str | None = None


class JobBrief(BaseModel):
    id: str
    status: str
    attempts: int
    max_attempts: int
    run_after: datetime | None
    last_error: str | None


class PushStatusOut(BaseModel):
    candidate_id: str
    status: PushStatusLiteral
    interview_id: str | None = None
    huntflow_applicant_id: int | None = None
    huntflow_vacancy_id: int | None = None
    huntflow_status_id: int | None = None
    last_pushed_at: datetime | None = None
    last_error: str | None = None
    report_share_url: str | None = None
    job: JobBrief | None = None
