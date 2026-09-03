"""Исходящие письма.

Каждое письмо сначала попадает в таблицу (outbox), а уже фоновая задача его
отправляет: постановка письма — в одной транзакции с изменением домена, а
отправка повторяется при сбое SMTP. Таблица же служит вкладкой «Письма» в
кабинете: без почтового сервера письма видны там.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk


class EmailStatus(enum.StrEnum):
    queued = "queued"
    sent = "sent"
    failed = "failed"


class EmailMessage(TimestampMixin, Base):
    __tablename__ = "email_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interviews.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, name="email_status", native_enum=False, length=16),
        default=EmailStatus.queued,
        nullable=False,
        index=True,
    )
    # Каким транспортом ушло: console (вкладка «Письма») или smtp.
    provider: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
