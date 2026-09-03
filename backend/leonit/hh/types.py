"""Типы данных клиента HH: то, что нужно предметному коду, без лишних полей API."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any


@dataclass(slots=True)
class HhTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(slots=True)
class HhEmployer:
    id: str
    name: str
    user_id: str = ""
    manager_account_id: str | None = None


@dataclass(slots=True)
class HhVacancy:
    id: str
    name: str
    url: str = ""
    description_html: str = ""
    key_skills: list[str] = field(default_factory=list)
    area: str = ""
    salary: str = ""
    published_at: datetime | None = None

    @property
    def description_text(self) -> str:
        return strip_html(self.description_html)


@dataclass(slots=True)
class HhResume:
    id: str
    first_name: str = ""
    last_name: str = ""
    middle_name: str = ""
    email: str | None = None
    phone: str | None = None
    title: str = ""
    experience: list[dict[str, Any]] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    url: str = ""

    @property
    def full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(part.strip() for part in parts if part and part.strip())

    def as_text(self) -> str:
        """Плоский текст резюме для карточки кандидата и модели-оценщика."""
        lines = [self.full_name]
        if self.title:
            lines.append(self.title)
        if self.skills:
            lines.append("Навыки: " + ", ".join(self.skills))
        for item in self.experience:
            period = " — ".join(p for p in (item.get("start"), item.get("end") or "н. в.") if p)
            head = " · ".join(p for p in (item.get("company"), item.get("position")) if p)
            lines.append(f"{period}: {head}".strip(": "))
            if item.get("description"):
                lines.append(strip_html(str(item["description"])))
        return "\n".join(line for line in lines if line)


@dataclass(slots=True)
class HhNegotiationInfo:
    id: str
    vacancy_id: str
    resume_id: str
    chat_id: str
    created_at: datetime | None = None
    state: str = "response"


@dataclass(slots=True)
class HhMessage:
    id: str
    author: str  # employer | applicant
    text: str
    created_at: datetime | None = None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("p", "br", "li", "div", "ul", "ol", "h1", "h2", "h3", "h4", "strong"):
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "li", "div", "ul", "ol", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(value: str) -> str:
    """HTML описания вакансии → текст с абзацами и маркерами списков."""
    parser = _TextExtractor()
    parser.feed(value or "")
    text = html.unescape("".join(parser.parts))
    text = "\n".join(line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def salary_text(salary: dict[str, Any] | None) -> str:
    if not salary:
        return ""
    low, high = salary.get("from"), salary.get("to")
    currency = str(salary.get("currency") or "").replace("RUR", "₽")
    if low and high:
        amount = f"{low:,}–{high:,}"
    elif low:
        amount = f"от {low:,}"
    elif high:
        amount = f"до {high:,}"
    else:
        return ""
    gross = "до вычета" if salary.get("gross") else "на руки"
    return f"{amount.replace(',', ' ')} {currency} {gross}".strip()
