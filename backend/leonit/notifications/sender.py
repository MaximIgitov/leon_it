"""Транспорт писем: SMTP или консоль.

Консольный транспорт — не заглушка для тестов, а рабочий режим стенда без
почтового сервера: письмо остаётся в outbox со статусом «отправлено», и его
можно открыть на вкладке «Письма».
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage as MimeMessage
from typing import Protocol

from leonit.core.config import Settings, get_settings
from leonit.core.logging import get_logger

log = get_logger(__name__)


class EmailSender(Protocol):
    name: str

    async def send(self, *, to_email: str, subject: str, body_text: str) -> None: ...


class ConsoleEmailSender:
    name = "console"

    async def send(self, *, to_email: str, subject: str, body_text: str) -> None:
        log.info("email.console to=%s subject=%s\n%s", to_email, subject, body_text)


class SmtpEmailSender:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send_sync(self, *, to_email: str, subject: str, body_text: str) -> None:
        settings = self.settings
        message = MimeMessage()
        message["From"] = settings.EMAIL_FROM
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body_text)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
            if settings.SMTP_STARTTLS:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            smtp.send_message(message)

    async def send(self, *, to_email: str, subject: str, body_text: str) -> None:
        # smtplib блокирующий; выносим в поток, чтобы не останавливать event loop.
        await asyncio.to_thread(
            self._send_sync, to_email=to_email, subject=subject, body_text=body_text
        )


_override: EmailSender | None = None


def get_email_sender(settings: Settings | None = None) -> EmailSender:
    if _override is not None:
        return _override
    settings = settings or get_settings()
    if settings.EMAIL_MODE == "smtp" and settings.SMTP_HOST:
        return SmtpEmailSender(settings)
    return ConsoleEmailSender()


def set_email_sender(sender: EmailSender | None) -> None:
    """Тестовый хук: подменить транспорт."""
    global _override
    _override = sender
