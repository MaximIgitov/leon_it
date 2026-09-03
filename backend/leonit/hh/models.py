"""Подключение HH.ru, привязки вакансий и отклики с состоянием диалога.

Одно подключение на организацию. Токены OAuth лежат только в зашифрованном
виде (``SecretBox``), секрет вебхука — хешем для поиска и шифротекстом для
показа владельцу. Отклик уникален по паре (подключение, id переговоров у HH):
повторная синхронизация не создаёт дублей.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leonit.core.db import Base, TimestampMixin, uuid_pk


class HhConnectionStatus(enum.StrEnum):
    connected = "connected"
    error = "error"
    disconnected = "disconnected"


class HhDialogState(enum.StrEnum):
    new = "new"
    greeting_sent = "greeting_sent"
    awaiting_slot = "awaiting_slot"
    link_sent = "link_sent"
    done = "done"
    declined = "declined"
    needs_recruiter = "needs_recruiter"


# Состояния, в которых бот больше ничего не делает сам.
TERMINAL_DIALOG_STATES = frozenset({HhDialogState.done, HhDialogState.declined})


class HhConnection(TimestampMixin, Base):
    __tablename__ = "hh_connections"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_hh_connection_org"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # fake — демо-аккаунт на фикстурах, real — настоящий OAuth.
    mode: Mapped[str] = mapped_column(String(8), default="fake", nullable=False)
    employer_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    employer_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    hh_user_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    manager_account_id: Mapped[str | None] = mapped_column(String(64))
    access_token_enc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[HhConnectionStatus] = mapped_column(
        Enum(HhConnectionStatus, name="hh_connection_status", native_enum=False, length=16),
        default=HhConnectionStatus.connected,
        nullable=False,
    )
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    webhook_secret_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    webhook_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vacancy_links: Mapped[list[HhVacancyLink]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class HhVacancyLink(TimestampMixin, Base):
    """Вакансия HH ↔ локальная вакансия и настройка диалога с откликнувшимися."""

    __tablename__ = "hh_vacancy_links"
    __table_args__ = (
        UniqueConstraint("connection_id", "hh_vacancy_id", name="uq_hh_vacancy_link"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hh_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    hh_vacancy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    hh_title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    hh_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    # {enabled, max_days, greeting, clarify, link} — см. hh.dialog.DEFAULT_DIALOG.
    dialog: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connection: Mapped[HhConnection] = relationship(back_populates="vacancy_links")
    negotiations: Mapped[list[HhNegotiation]] = relationship(
        back_populates="vacancy_link", cascade="all, delete-orphan"
    )


class HhNegotiation(TimestampMixin, Base):
    """Отклик кандидата на HH и состояние диалога с ним."""

    __tablename__ = "hh_negotiations"
    __table_args__ = (
        UniqueConstraint("connection_id", "negotiation_id", name="uq_hh_negotiation"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hh_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vacancy_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hh_vacancy_links.id", ondelete="CASCADE"), index=True, nullable=False
    )
    negotiation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    resume_id: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interviews.id", ondelete="SET NULL"), index=True
    )
    state: Mapped[HhDialogState] = mapped_column(
        Enum(HhDialogState, name="hh_dialog_state", native_enum=False, length=16),
        default=HhDialogState.new,
        nullable=False,
        index=True,
    )
    chosen_date: Mapped[date | None] = mapped_column(Date)
    # [{role: bot|candidate|recruiter, text, at, hh_message_id}]
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    last_hh_message_id: Mapped[str | None] = mapped_column(String(64))
    clarify_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vacancy_link: Mapped[HhVacancyLink] = relationship(back_populates="negotiations")
