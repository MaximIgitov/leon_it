"""Трёхшаговый диалог с откликнувшимся в чате HH.

Шаги: приветствие с вопросом об удобном дне → (если не разобрали) уточнение →
ссылка на интервью. Состояния отклика: ``new → greeting_sent → awaiting_slot →
link_sent → done`` с ветками ``declined`` и ``needs_recruiter``. Каждая отправка
идемпотентна: ключ выводится из отклика и шага, уже отправленный шаг не
повторяется, история сообщений хранится в самом отклике.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.accounts.models import Organization
from leonit.accounts.security import generate_link_token, hash_link_token
from leonit.ai.providers.base import LLMProvider
from leonit.candidates.models import Candidate, Interview, InterviewStatus
from leonit.candidates.service import (
    estimated_minutes,
    interview_link,
    remember_link_token,
    transition,
)
from leonit.core.logging import get_logger
from leonit.core.time import utcnow
from leonit.hh.client import HhClient
from leonit.hh.models import HhDialogState, HhNegotiation, HhVacancyLink
from leonit.hh.slots import extract_slot
from leonit.hh.types import HhMessage
from leonit.notifications.service import queue_email
from leonit.notifications.templates import invitation_email
from leonit.vacancies.models import Vacancy, VacancyStatus

log = get_logger(__name__)

DEFAULT_MAX_DAYS = 7
PLACEHOLDERS: tuple[str, ...] = ("candidate_name", "vacancy_title", "link", "days", "date")
DEFAULT_DIALOG: dict[str, Any] = {
    "enabled": True,
    "max_days": DEFAULT_MAX_DAYS,
    "greeting": (
        "Здравствуйте, {candidate_name}! Спасибо за отклик на вакансию «{vacancy_title}». "
        "Первый этап — короткое видеоинтервью онлайн: несколько вопросов, ответы "
        "записываются на камеру, займёт около 20 минут, пройти можно с телефона или "
        "ноутбука. В какой день в ближайшие {days} дней вам удобно? Напишите, "
        "пожалуйста, день — например, «завтра» или «в пятницу»."
    ),
    "clarify": (
        "Извините, не удалось разобрать день. Напишите, пожалуйста, когда вам удобно "
        "пройти видеоинтервью в ближайшие {days} дней — например, «послезавтра», "
        "«в четверг» или дату."
    ),
    "link": (
        "Отлично! Вот ваша ссылка на видеоинтервью по вакансии «{vacancy_title}»: {link}\n"
        "Она действует до {date} включительно. Перед началом система проверит камеру и "
        "микрофон, будет тренировочный вопрос. Удачи!"
    ),
}
# Статусы интервью, после которых диалог считается завершённым.
_FINISHED_STATUSES = frozenset(
    {
        InterviewStatus.completed,
        InterviewStatus.processing,
        InterviewStatus.evaluated,
        InterviewStatus.reviewed,
        InterviewStatus.advanced,
        InterviewStatus.rejected,
    }
)
_ACTIVE_INTERVIEW_STATUSES = (
    InterviewStatus.cancelled,
    InterviewStatus.expired,
    InterviewStatus.rejected,
)
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_IDEMPOTENCY_NAMESPACE = uuid.UUID("7f8a2c0e-6c3b-4b7e-9d21-0f2b5c9e1a11")


@dataclass(frozen=True, slots=True)
class DialogConfig:
    enabled: bool
    max_days: int
    greeting: str
    clarify: str
    link: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_days": self.max_days,
            "greeting": self.greeting,
            "clarify": self.clarify,
            "link": self.link,
        }


def dialog_config(raw: dict[str, Any] | None) -> DialogConfig:
    """Настройка диалога с подстановкой значений по умолчанию для пропущенных полей."""
    data = {**DEFAULT_DIALOG, **(raw or {})}
    try:
        max_days = max(1, min(int(data.get("max_days") or DEFAULT_MAX_DAYS), 60))
    except (TypeError, ValueError):
        max_days = DEFAULT_MAX_DAYS
    return DialogConfig(
        enabled=bool(data.get("enabled", True)),
        max_days=max_days,
        greeting=str(data.get("greeting") or DEFAULT_DIALOG["greeting"]),
        clarify=str(data.get("clarify") or DEFAULT_DIALOG["clarify"]),
        link=str(data.get("link") or DEFAULT_DIALOG["link"]),
    )


def render(template: str, values: dict[str, Any]) -> str:
    """Подставить плейсхолдеры; неизвестные остаются как есть (не str.format)."""
    return _PLACEHOLDER_RE.sub(
        lambda match: str(values[match.group(1)]) if match.group(1) in values else match.group(0),
        template,
    )


def format_date_ru(value: date) -> str:
    return f"{value.day} {_MONTHS_GENITIVE[value.month - 1]}"


def idempotency_key(negotiation_id: uuid.UUID, step: str) -> str:
    """Ключ отправки: один и тот же для отклика и шага при любых повторах."""
    return str(uuid.uuid5(_IDEMPOTENCY_NAMESPACE, f"{negotiation_id}:{step}"))


def link_expires_at(chosen: date) -> datetime:
    """Ссылка живёт до конца дня, следующего за выбранным."""
    return datetime.combine(chosen + timedelta(days=1), time(23, 59, 59), tzinfo=UTC)


# Резюме без e-mail получает синтетический адрес: письма на него не уходят.
SYNTHETIC_EMAIL_DOMAIN = "candidates.hh.example"


def is_synthetic_email(email: str) -> bool:
    return email.endswith(f"@{SYNTHETIC_EMAIL_DOMAIN}")


class DialogRunner:
    """Шаги диалога по одному отклику. Не коммитит: это делает синхронизация."""

    def __init__(
        self,
        session: AsyncSession,
        client: HhClient,
        *,
        llm: LLMProvider | None,
    ) -> None:
        self.session = session
        self.client = client
        self.llm = llm

    # --- сообщения ------------------------------------------------------------

    async def pull(self, negotiation: HhNegotiation) -> list[HhMessage]:
        """Забрать новые сообщения чата в историю; вернуть новые реплики кандидата."""
        if not negotiation.chat_id:
            return []
        items = await self.client.messages(
            negotiation.chat_id, after_message_id=negotiation.last_hh_message_id
        )
        known = {entry.get("hh_message_id") for entry in negotiation.messages}
        entries = list(negotiation.messages)
        fresh: list[HhMessage] = []
        for item in items:
            if not item.id or item.id in known:
                continue
            role = "candidate" if item.author == "applicant" else "recruiter"
            entries.append(
                {
                    "role": role,
                    "text": item.text,
                    "at": (item.created_at or utcnow()).isoformat(),
                    "hh_message_id": item.id,
                }
            )
            known.add(item.id)
            negotiation.last_hh_message_id = item.id
            if role == "candidate":
                fresh.append(item)
        negotiation.messages = entries
        return fresh

    async def _send(self, negotiation: HhNegotiation, step: str, text: str) -> None:
        if any(entry.get("step") == step for entry in negotiation.messages):
            return  # шаг уже отправлен: повторная синхронизация не дублирует
        message = await self.client.send_message(
            negotiation.chat_id, text, idempotency_key=idempotency_key(negotiation.id, step)
        )
        entry = {
            "role": "bot",
            "step": step,
            "text": text,
            "at": ((message.created_at if message else None) or utcnow()).isoformat(),
            "hh_message_id": message.id if message else None,
        }
        negotiation.messages = [*negotiation.messages, entry]
        if message is not None and message.id:
            negotiation.last_hh_message_id = message.id

    # --- шаги -----------------------------------------------------------------

    def _values(
        self, candidate: Candidate, vacancy: Vacancy, config: DialogConfig
    ) -> dict[str, Any]:
        return {
            "candidate_name": _first_name(candidate.full_name),
            "vacancy_title": vacancy.title,
            "days": config.max_days,
        }

    async def start(
        self,
        negotiation: HhNegotiation,
        link: HhVacancyLink,
        vacancy: Vacancy,
        candidate: Candidate,
    ) -> None:
        config = dialog_config(link.dialog)
        text = render(config.greeting, self._values(candidate, vacancy, config))
        await self._send(negotiation, "greeting", text)
        negotiation.state = HhDialogState.greeting_sent

    async def advance(
        self,
        negotiation: HhNegotiation,
        link: HhVacancyLink,
        vacancy: Vacancy,
        candidate: Candidate,
        organization: Organization,
        fresh: list[HhMessage],
    ) -> None:
        """Реакция на новые реплики кандидата в greeting_sent / awaiting_slot."""
        if not fresh:
            return
        config = dialog_config(link.dialog)
        text = "\n".join(item.text for item in fresh)
        slot = await extract_slot(
            text, today=utcnow().date(), max_days=config.max_days, llm=self.llm
        )
        if slot.kind == "declined":
            negotiation.state = HhDialogState.declined
            return
        if slot.kind == "date" and slot.date is not None:
            await self.send_link(
                negotiation, link, vacancy, candidate, organization, chosen=slot.date
            )
            return
        if negotiation.clarify_count == 0:
            negotiation.clarify_count += 1
            await self._send(
                negotiation,
                "clarify",
                render(config.clarify, self._values(candidate, vacancy, config)),
            )
            negotiation.state = HhDialogState.awaiting_slot
            return
        negotiation.state = HhDialogState.needs_recruiter

    async def send_link(
        self,
        negotiation: HhNegotiation,
        link: HhVacancyLink,
        vacancy: Vacancy,
        candidate: Candidate,
        organization: Organization,
        *,
        chosen: date | None,
        expires_at: datetime | None = None,
        invited_by_user_id: uuid.UUID | None = None,
    ) -> Interview:
        """Создать (или обновить) приглашение и отправить ссылку — шаг 3."""
        if vacancy.status != VacancyStatus.published:
            raise ValueError("Вакансия не опубликована — ссылку на интервью выдать нельзя")
        config = dialog_config(link.dialog)
        expires = expires_at or (
            link_expires_at(chosen)
            if chosen is not None
            else utcnow() + timedelta(days=vacancy.invitation_days)
        )
        interview, token = await self._ensure_interview(
            negotiation, vacancy, candidate, expires_at=expires, invited_by=invited_by_user_id
        )
        url = interview_link(token)
        values = {
            **self._values(candidate, vacancy, config),
            "link": url,
            "date": format_date_ru(expires.date()),
        }
        await self._send(negotiation, "link", render(config.link, values))
        negotiation.chosen_date = chosen
        negotiation.state = HhDialogState.link_sent
        if not is_synthetic_email(candidate.email):
            subject, body = invitation_email(
                candidate_name=candidate.full_name,
                organization_name=organization.name,
                vacancy_title=vacancy.title,
                link=url,
                expires_at=expires,
                question_count=len(vacancy.questions),
                estimated_minutes=estimated_minutes(vacancy),
            )
            await queue_email(
                self.session,
                organization_id=organization.id,
                to_email=candidate.email,
                subject=subject,
                body_text=body,
                kind="interview.invitation",
                interview_id=interview.id,
            )
        return interview

    async def _ensure_interview(
        self,
        negotiation: HhNegotiation,
        vacancy: Vacancy,
        candidate: Candidate,
        *,
        expires_at: datetime,
        invited_by: uuid.UUID | None,
    ) -> tuple[Interview, str]:
        token = generate_link_token()
        interview = await self.session.scalar(
            select(Interview).where(
                Interview.candidate_id == candidate.id,
                Interview.vacancy_id == vacancy.id,
                Interview.status.notin_(list(_ACTIVE_INTERVIEW_STATUSES)),
            )
        )
        if interview is None:
            interview = Interview(
                organization_id=vacancy.organization_id,
                vacancy_id=vacancy.id,
                candidate_id=candidate.id,
                token_hash=hash_link_token(token),
                invited_by_user_id=invited_by,
                expires_at=expires_at,
                external_ref=f"hh:{negotiation.negotiation_id}",
            )
            self.session.add(interview)
        else:
            # Активное приглашение уже есть: для отправки в чат выпускаем новую
            # ссылку (как «переслать»).
            interview.token_hash = hash_link_token(token)
            interview.expires_at = expires_at
            interview.external_ref = interview.external_ref or f"hh:{negotiation.negotiation_id}"
            if interview.status == InterviewStatus.expired:
                transition(interview, InterviewStatus.invited)
        remember_link_token(interview, token)
        await self.session.flush()
        negotiation.interview_id = interview.id
        return interview, token

    async def refresh_done(self, negotiation: HhNegotiation) -> None:
        if negotiation.state != HhDialogState.link_sent or negotiation.interview_id is None:
            return
        interview = await self.session.get(Interview, negotiation.interview_id)
        if interview is not None and interview.status in _FINISHED_STATUSES:
            negotiation.state = HhDialogState.done


def _first_name(full_name: str) -> str:
    """«Фамилия Имя Отчество» из HH → «Имя»; одно слово — как есть."""
    parts = full_name.split()
    if len(parts) >= 2:
        return parts[1]
    return full_name
