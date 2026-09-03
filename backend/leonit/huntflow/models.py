"""Подключение к Huntflow, привязки вакансий и соискатели.

Одно подключение на организацию: персональный токен хранится только в
зашифрованном виде (``SecretBox``), в открытом — id и название аккаунта и
режим клиента (``real``/``fake``), по которому сервис выбирает реализацию.
Привязка вакансии говорит, в какую вакансию Huntflow и с каким статусом
передавать кандидатов; строка соискателя связывает локального кандидата с
``applicant_id`` и хранит результат последней передачи.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from leonit.core.db import Base, TimestampMixin, uuid_pk


class HuntflowMode(enum.StrEnum):
    real = "real"
    fake = "fake"


class HuntflowConnectionStatus(enum.StrEnum):
    # Токен принят, аккаунт выбран — интеграция работает.
    active = "active"
    # Токен принят, но у пользователя несколько аккаунтов: нужно выбрать.
    needs_account = "needs_account"
    # Huntflow отклонил токен (401) или подключение не удалось.
    error = "error"


class HuntflowPushStatus(enum.StrEnum):
    # Соискатель известен (импортирован), но кандидата ещё не передавали.
    linked = "linked"
    queued = "queued"
    pushing = "pushing"
    pushed = "pushed"
    error = "error"


class HuntflowConnection(TimestampMixin, Base):
    __tablename__ = "huntflow_connections"

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    mode: Mapped[HuntflowMode] = mapped_column(
        Enum(HuntflowMode, name="huntflow_mode", native_enum=False, length=8), nullable=False
    )
    # Fernet-шифротекст персонального токена; у демо-подключения пуст.
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[int | None] = mapped_column(Integer)
    account_name: Mapped[str | None] = mapped_column(String(255))
    # Кому принадлежит токен (GET /me) — видно на странице интеграции.
    owner_name: Mapped[str | None] = mapped_column(String(255))
    owner_email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[HuntflowConnectionStatus] = mapped_column(
        Enum(
            HuntflowConnectionStatus,
            name="huntflow_connection_status",
            native_enum=False,
            length=16,
        ),
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class HuntflowVacancyLink(TimestampMixin, Base):
    __tablename__ = "huntflow_vacancy_links"
    __table_args__ = (
        UniqueConstraint("organization_id", "vacancy_id", name="uq_huntflow_link_vacancy"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("huntflow_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    huntflow_vacancy_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Снимок названия на момент привязки: список вакансий Huntflow может быть недоступен.
    huntflow_vacancy_title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Статус воронки, в который переводится соискатель при передаче; None — первый.
    status_id: Mapped[int | None] = mapped_column(Integer)
    status_name: Mapped[str | None] = mapped_column(String(255))
    last_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HuntflowApplicant(TimestampMixin, Base):
    __tablename__ = "huntflow_applicants"
    __table_args__ = (
        UniqueConstraint("organization_id", "candidate_id", name="uq_huntflow_applicant_candidate"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("huntflow_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Интервью, по которому передан отчёт; пусто у импортированных соискателей.
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interviews.id", ondelete="SET NULL")
    )
    huntflow_applicant_id: Mapped[int | None] = mapped_column(Integer, index=True)
    huntflow_vacancy_id: Mapped[int | None] = mapped_column(Integer)
    huntflow_status_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[HuntflowPushStatus] = mapped_column(
        Enum(HuntflowPushStatus, name="huntflow_push_status", native_enum=False, length=16),
        nullable=False,
        default=HuntflowPushStatus.linked,
    )
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    pushed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Ссылка на отчёт, отправленная в Huntflow: повторная передача переиспользует её.
    report_share_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("report_shares.id", ondelete="SET NULL")
    )
    report_share_url: Mapped[str | None] = mapped_column(Text)
    # Последняя задача huntflow.push — по ней страница показывает попытки и ошибку очереди.
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
