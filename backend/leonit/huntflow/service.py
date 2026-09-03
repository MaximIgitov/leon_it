"""Сервис интеграции с Huntflow.

Режим клиента выбирается при подключении и хранится в ``HuntflowConnection.mode``:
``HUNTFLOW_MODE=auto`` даёт реальный клиент при подключении по токену и
фейковый при «Подключить демо»; ``fake`` — всегда фикстуры; ``real`` — демо
запрещено. Все дальнейшие вызовы берут клиент по режиму подключения, поэтому
сервис не отличает демо от настоящего аккаунта.

Передача кандидата идёт через очередь (``huntflow.push``): ручка ставит задачу и
отвечает 202, ``perform_push`` в воркере находит или создаёт соискателя,
выпускает ссылку на отчёт (30 дней, через ``ReportService`` от имени
пользователя, который нажал кнопку) и привязывает соискателя к вакансии с
комментарием. Сетевые сбои пробрасываются наружу — очередь повторит; ответы
4xx и отклонённый токен повтором не лечатся, задача завершается с ошибкой в
строке соискателя.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.accounts.models import User
from leonit.accounts.service import AccountsService
from leonit.candidates.models import Candidate, CandidateSource, Interview, InterviewStatus
from leonit.candidates.service import CandidateService, InterviewService
from leonit.core.authz import Actor, authorize
from leonit.core.config import Settings, get_settings
from leonit.core.crypto import SecretBoxError, get_secret_box
from leonit.core.errors import (
    ConflictError,
    NotFoundError,
    UpstreamError,
    ValidationFailedError,
)
from leonit.core.logging import get_logger
from leonit.core.time import aware, utcnow
from leonit.huntflow.client import (
    ApplicantCreate,
    FakeHuntflowClient,
    HuntflowAccount,
    HuntflowApplicantRecord,
    HuntflowAuthError,
    HuntflowClient,
    HuntflowError,
    HuntflowStatus,
    HuntflowUnavailableError,
    HuntflowVacancy,
    RealHuntflowClient,
    split_full_name,
)
from leonit.huntflow.models import (
    HuntflowApplicant,
    HuntflowConnection,
    HuntflowConnectionStatus,
    HuntflowMode,
    HuntflowPushStatus,
    HuntflowVacancyLink,
)
from leonit.huntflow.schemas import ConnectIn, LinkIn, PushIn
from leonit.jobs import service as jobs
from leonit.jobs.models import Job
from leonit.reports.models import ReportShare
from leonit.reports.schemas import ShareCreate
from leonit.reports.service import ReportService, share_status, share_url
from leonit.vacancies.models import Vacancy

log = get_logger(__name__)

PUSH_JOB = "huntflow.push"
REPORT_SHARE_DAYS = 30
REPORT_SHARE_LABEL = "Huntflow"
EXTERNAL_REF_PREFIX = "huntflow:"
_MAX_ERROR_CHARS = 2000

INTERVIEW_STATUS_LABELS: dict[str, str] = {
    "invited": "кандидат приглашён",
    "opened": "кандидат открыл ссылку",
    "consented": "кандидат дал согласие",
    "in_progress": "кандидат проходит интервью",
    "completed": "интервью завершено, идёт обработка",
    "processing": "интервью завершено, идёт обработка",
    "evaluated": "интервью оценено",
    "reviewed": "интервью просмотрено",
    "advanced": "кандидат прошёл дальше",
    "rejected": "кандидату отказано",
    "expired": "срок ссылки истёк",
    "cancelled": "интервью отменено",
}
RECOMMENDATION_LABELS: dict[str, str] = {
    "fit": "подходит",
    "no_fit": "не подходит",
    "needs_check": "нужна проверка",
}
DECISION_LABELS: dict[str, str] = {"advance": "дальше", "reject": "отказ", "hold": "на паузе"}


def demo_available(settings: Settings) -> bool:
    return settings.HUNTFLOW_MODE != "real"


def resolve_mode(settings: Settings, *, demo: bool) -> HuntflowMode:
    """Какой клиент использовать для нового подключения (см. докстринг модуля)."""
    if settings.HUNTFLOW_MODE == "fake":
        return HuntflowMode.fake
    if settings.HUNTFLOW_MODE == "real":
        if demo:
            raise ValidationFailedError("Демо-режим отключён (HUNTFLOW_MODE=real)")
        return HuntflowMode.real
    return HuntflowMode.fake if demo else HuntflowMode.real


def _truncate(text: str) -> str:
    return text[:_MAX_ERROR_CHARS]


class HuntflowService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    # ------------------------------------------------------------ подключение

    async def connection(self, organization_id: UUID) -> HuntflowConnection | None:
        return await self.session.scalar(
            select(HuntflowConnection).where(HuntflowConnection.organization_id == organization_id)
        )

    async def _require_connection(self, organization_id: UUID) -> HuntflowConnection:
        connection = await self.connection(organization_id)
        if connection is None:
            raise ConflictError("Huntflow не подключён")
        return connection

    async def _require_active(self, organization_id: UUID) -> HuntflowConnection:
        connection = await self._require_connection(organization_id)
        if connection.status == HuntflowConnectionStatus.needs_account:
            raise ConflictError("Выберите аккаунт Huntflow, чтобы продолжить")
        if connection.status != HuntflowConnectionStatus.active or connection.account_id is None:
            raise ConflictError(connection.last_error or "Подключение Huntflow в состоянии ошибки")
        return connection

    def client(self, connection: HuntflowConnection) -> HuntflowClient:
        if connection.mode == HuntflowMode.fake:
            return FakeHuntflowClient(str(connection.organization_id))
        if not connection.token_encrypted:
            raise ConflictError("У подключения Huntflow нет токена — подключите заново")
        try:
            token = get_secret_box().decrypt(connection.token_encrypted)
        except SecretBoxError as exc:
            connection.status = HuntflowConnectionStatus.error
            connection.last_error = "Не удалось расшифровать токен: ключ шифрования сменился"
            raise ConflictError(connection.last_error) from exc
        return self._real_client(token)

    def _real_client(self, token: str) -> HuntflowClient:
        return RealHuntflowClient(
            token,
            base_url=self.settings.HUNTFLOW_API_BASE,
            timeout_s=self.settings.HUNTFLOW_TIMEOUT_S,
        )

    async def _mark_error(self, connection: HuntflowConnection, error: HuntflowError) -> None:
        connection.status = HuntflowConnectionStatus.error
        connection.last_error = _truncate(str(error))
        connection.last_checked_at = utcnow()
        await self.session.commit()

    async def _raise_from(self, connection: HuntflowConnection, error: HuntflowError) -> None:
        """Отклонённый токен переводит подключение в error; остальное — 502."""
        if isinstance(error, HuntflowAuthError):
            await self._mark_error(connection, error)
        raise UpstreamError(str(error)) from error

    async def status(
        self, actor: Actor
    ) -> tuple[HuntflowConnection | None, list[HuntflowAccount], int]:
        authorize(actor, "integrations.read")
        connection = await self.connection(actor.organization_id)
        if connection is None:
            return None, [], 0
        accounts: list[HuntflowAccount] = []
        if connection.status == HuntflowConnectionStatus.needs_account:
            client = self.client(connection)
            try:
                accounts = await client.accounts()
            except HuntflowError as error:
                log.warning(
                    "huntflow accounts unavailable org=%s: %s", actor.organization_id, error
                )
            finally:
                await client.aclose()
        links = await self.session.scalar(
            select(func.count())
            .select_from(HuntflowVacancyLink)
            .where(HuntflowVacancyLink.connection_id == connection.id)
        )
        return connection, accounts, int(links or 0)

    async def connect(self, actor: Actor, payload: ConnectIn) -> HuntflowConnection:
        authorize(actor, "integrations.manage")
        mode = resolve_mode(self.settings, demo=payload.demo)
        connection = await self.connection(actor.organization_id)
        if connection is None:
            connection = HuntflowConnection(
                organization_id=actor.organization_id,
                mode=mode,
                status=HuntflowConnectionStatus.error,
            )
            self.session.add(connection)
        connection.mode = mode
        connection.token_encrypted = (
            get_secret_box().encrypt(payload.token)
            if mode == HuntflowMode.real and payload.token
            else None
        )
        connection.connected_by_user_id = actor.user.id
        connection.account_id = None
        connection.account_name = None
        connection.last_error = None
        connection.last_checked_at = utcnow()
        client = (
            FakeHuntflowClient(str(actor.organization_id))
            if mode == HuntflowMode.fake
            else self._real_client(payload.token or "")
        )
        try:
            me = await client.me()
            accounts = await client.accounts()
        except HuntflowError as error:
            connection.status = HuntflowConnectionStatus.error
            connection.last_error = _truncate(str(error))
            await self.session.commit()
            if isinstance(error, HuntflowAuthError):
                raise ValidationFailedError(str(error)) from error
            raise UpstreamError(str(error)) from error
        finally:
            await client.aclose()
        connection.owner_name = me.name
        connection.owner_email = me.email
        self._select_account(connection, accounts, payload.account_id)
        await self.session.commit()
        return connection

    @staticmethod
    def _select_account(
        connection: HuntflowConnection, accounts: list[HuntflowAccount], account_id: int | None
    ) -> None:
        if not accounts:
            connection.status = HuntflowConnectionStatus.error
            connection.last_error = "У токена нет доступных аккаунтов Huntflow"
            return
        chosen: HuntflowAccount | None = None
        if account_id is not None:
            chosen = next((a for a in accounts if a.id == account_id), None)
            if chosen is None:
                raise ValidationFailedError("Такого аккаунта нет среди доступных токену")
        elif len(accounts) == 1:
            chosen = accounts[0]
        if chosen is None:
            connection.status = HuntflowConnectionStatus.needs_account
            connection.account_id = None
            connection.account_name = None
            return
        connection.account_id = chosen.id
        connection.account_name = chosen.name
        connection.status = HuntflowConnectionStatus.active
        connection.last_error = None

    async def select_account(self, actor: Actor, account_id: int) -> HuntflowConnection:
        authorize(actor, "integrations.manage")
        connection = await self._require_connection(actor.organization_id)
        client = self.client(connection)
        try:
            accounts = await client.accounts()
        except HuntflowError as error:
            await self._raise_from(connection, error)
        finally:
            await client.aclose()
        self._select_account(connection, accounts, account_id)
        connection.last_checked_at = utcnow()
        await self.session.commit()
        return connection

    async def disconnect(self, actor: Actor) -> None:
        authorize(actor, "integrations.manage")
        connection = await self.connection(actor.organization_id)
        if connection is None:
            return
        # Привязки и строки соискателей уходят каскадом вместе с токеном.
        await self.session.delete(connection)
        await self.session.commit()

    # ---------------------------------------------------------------- вакансии

    async def list_vacancies(
        self, actor: Actor
    ) -> tuple[
        list[HuntflowVacancy], list[HuntflowStatus], list[tuple[HuntflowVacancyLink, Vacancy]]
    ]:
        authorize(actor, "integrations.read")
        connection = await self._require_active(actor.organization_id)
        client = self.client(connection)
        try:
            vacancies = await client.vacancies(connection.account_id)  # type: ignore[arg-type]
            statuses = await client.statuses(connection.account_id)  # type: ignore[arg-type]
        except HuntflowError as error:
            await self._raise_from(connection, error)
        finally:
            await client.aclose()
        return vacancies, statuses, await self.links(actor)

    async def links(self, actor: Actor) -> list[tuple[HuntflowVacancyLink, Vacancy]]:
        authorize(actor, "integrations.read")
        rows = await self.session.execute(
            select(HuntflowVacancyLink, Vacancy)
            .join(Vacancy, Vacancy.id == HuntflowVacancyLink.vacancy_id)
            .where(HuntflowVacancyLink.organization_id == actor.organization_id)
            .order_by(HuntflowVacancyLink.created_at.desc())
        )
        return [(link, vacancy) for link, vacancy in rows.all()]

    async def _vacancy(self, actor: Actor, vacancy_id: UUID) -> Vacancy:
        vacancy = await self.session.scalar(
            select(Vacancy).where(
                Vacancy.id == vacancy_id, Vacancy.organization_id == actor.organization_id
            )
        )
        if vacancy is None:
            raise NotFoundError("Вакансия не найдена")
        return vacancy

    async def _link_for(
        self, organization_id: UUID, vacancy_id: UUID
    ) -> HuntflowVacancyLink | None:
        return await self.session.scalar(
            select(HuntflowVacancyLink).where(
                HuntflowVacancyLink.organization_id == organization_id,
                HuntflowVacancyLink.vacancy_id == vacancy_id,
            )
        )

    async def link_vacancy(
        self, actor: Actor, vacancy_id: UUID, payload: LinkIn
    ) -> tuple[HuntflowVacancyLink, Vacancy]:
        authorize(actor, "vacancy.write", vacancy_id=vacancy_id)
        authorize(actor, "integrations.read")
        connection = await self._require_active(actor.organization_id)
        vacancy = await self._vacancy(actor, vacancy_id)
        client = self.client(connection)
        try:
            remote = await client.vacancies(connection.account_id)  # type: ignore[arg-type]
            statuses = await client.statuses(connection.account_id)  # type: ignore[arg-type]
        except HuntflowError as error:
            await self._raise_from(connection, error)
        finally:
            await client.aclose()
        target = next((v for v in remote if v.id == payload.huntflow_vacancy_id), None)
        if target is None:
            raise ValidationFailedError("Вакансия Huntflow не найдена в аккаунте")
        status: HuntflowStatus | None = None
        if payload.status_id is not None:
            status = next((s for s in statuses if s.id == payload.status_id), None)
            if status is None:
                raise ValidationFailedError("Статус воронки Huntflow не найден")
        link = await self._link_for(actor.organization_id, vacancy.id)
        if link is None:
            link = HuntflowVacancyLink(
                organization_id=actor.organization_id,
                connection_id=connection.id,
                vacancy_id=vacancy.id,
                huntflow_vacancy_id=target.id,
                huntflow_vacancy_title=target.position,
            )
            self.session.add(link)
        link.connection_id = connection.id
        link.huntflow_vacancy_id = target.id
        link.huntflow_vacancy_title = target.position
        link.status_id = status.id if status else None
        link.status_name = status.name if status else None
        await self.session.commit()
        return link, vacancy

    async def unlink_vacancy(self, actor: Actor, vacancy_id: UUID) -> None:
        authorize(actor, "vacancy.write", vacancy_id=vacancy_id)
        authorize(actor, "integrations.read")
        link = await self._link_for(actor.organization_id, vacancy_id)
        if link is None:
            raise NotFoundError("Вакансия не привязана к Huntflow")
        await self.session.delete(link)
        await self.session.commit()

    # ------------------------------------------------------------------ импорт

    async def import_applicants(self, actor: Actor, vacancy_id: UUID) -> dict[str, int]:
        authorize(actor, "candidate.write", vacancy_id=vacancy_id)
        authorize(actor, "integrations.read")
        connection = await self._require_active(actor.organization_id)
        link = await self._link_for(actor.organization_id, vacancy_id)
        if link is None:
            raise ConflictError("Сначала привяжите вакансию к вакансии Huntflow")
        client = self.client(connection)
        try:
            records = await client.applicants(
                connection.account_id,  # type: ignore[arg-type]
                vacancy_id=link.huntflow_vacancy_id,
            )
        except HuntflowError as error:
            await self._raise_from(connection, error)
        finally:
            await client.aclose()
        candidates = CandidateService(self.session)
        created = existing = skipped = 0
        seen: set[str] = set()
        for record in records:
            email = (record.email or "").lower()
            if not email or email in seen:
                skipped += 1
                continue
            seen.add(email)
            candidate, is_new = await candidates.get_or_create(
                actor,
                full_name=record.full_name or email.split("@", 1)[0],
                email=email,
                source=CandidateSource.huntflow,
                phone=record.phone,
                notes=f"Импортирован из Huntflow ({record.position})" if record.position else "",
            )
            if is_new:
                created += 1
                candidate.external_ref = f"{EXTERNAL_REF_PREFIX}{record.id}"
            else:
                existing += 1
                if candidate.external_ref is None:
                    candidate.external_ref = f"{EXTERNAL_REF_PREFIX}{record.id}"
            row = await self._applicant_row(actor.organization_id, candidate.id)
            if row is None:
                row = HuntflowApplicant(
                    organization_id=actor.organization_id,
                    connection_id=connection.id,
                    candidate_id=candidate.id,
                    status=HuntflowPushStatus.linked,
                )
                self.session.add(row)
            if row.huntflow_applicant_id is None:
                row.huntflow_applicant_id = record.id
        link.last_imported_at = utcnow()
        await self.session.commit()
        return {
            "total": len(records),
            "created": created,
            "existing": existing,
            "skipped": skipped,
        }

    # ---------------------------------------------------------------- передача

    async def _applicant_row(
        self, organization_id: UUID, candidate_id: UUID
    ) -> HuntflowApplicant | None:
        return await self.session.scalar(
            select(HuntflowApplicant).where(
                HuntflowApplicant.organization_id == organization_id,
                HuntflowApplicant.candidate_id == candidate_id,
            )
        )

    async def push_candidate(
        self, actor: Actor, candidate_id: UUID, payload: PushIn
    ) -> tuple[HuntflowApplicant, Job | None]:
        authorize(actor, "candidate.write")
        authorize(actor, "integrations.read")
        connection = await self._require_active(actor.organization_id)
        candidate = await CandidateService(self.session).get(actor, candidate_id)
        interview = await self._interview_for_push(actor, candidate, payload.interview_id)
        authorize(actor, "candidate.write", vacancy_id=interview.vacancy_id)
        row = await self._applicant_row(actor.organization_id, candidate.id)
        if row is None:
            row = HuntflowApplicant(
                organization_id=actor.organization_id,
                connection_id=connection.id,
                candidate_id=candidate.id,
            )
            self.session.add(row)
        if row.status == HuntflowPushStatus.pushing:
            raise ConflictError("Передача уже выполняется")
        row.connection_id = connection.id
        row.interview_id = interview.id
        row.status = HuntflowPushStatus.queued
        row.last_error = None
        row.pushed_by_user_id = actor.user.id
        await self.session.flush()
        job = await jobs.enqueue(
            self.session,
            PUSH_JOB,
            {"huntflow_applicant_id": str(row.id)},
            dedupe_key=f"huntflow:push:{row.id}",
        )
        row.job_id = job.id
        await self.session.commit()
        return row, job

    async def _interview_for_push(
        self, actor: Actor, candidate: Candidate, interview_id: str | None
    ) -> Interview:
        interviews = InterviewService(self.session)
        if interview_id:
            interview = await interviews.get(actor, UUID(interview_id))
            if interview.candidate_id != candidate.id:
                raise ValidationFailedError("Интервью не принадлежит этому кандидату")
            if await self._link_for(actor.organization_id, interview.vacancy_id) is None:
                raise ValidationFailedError(
                    "Вакансия этого интервью не привязана к Huntflow — привяжите её на "
                    "странице интеграции"
                )
            return interview
        linked = {
            link.vacancy_id
            for link in await self.session.scalars(
                select(HuntflowVacancyLink).where(
                    HuntflowVacancyLink.organization_id == actor.organization_id
                )
            )
        }
        if not linked:
            raise ValidationFailedError("Ни одна вакансия не привязана к Huntflow")
        candidates_interviews = await interviews.list(actor, candidate_id=candidate.id)
        for interview in candidates_interviews:
            if interview.vacancy_id in linked and interview.status != InterviewStatus.cancelled:
                return interview
        raise ValidationFailedError("У кандидата нет интервью по вакансии, привязанной к Huntflow")

    async def push_status(
        self, actor: Actor, candidate_id: UUID
    ) -> tuple[Candidate, HuntflowApplicant | None, Job | None]:
        authorize(actor, "integrations.read")
        candidate = await CandidateService(self.session).get(actor, candidate_id)
        row = await self._applicant_row(actor.organization_id, candidate.id)
        job = await self.session.get(Job, row.job_id) if row is not None and row.job_id else None
        return candidate, row, job


# ------------------------------------------------------------------ фоновая задача


async def perform_push(session: AsyncSession, row_id: UUID) -> dict[str, Any]:
    """Тело задачи ``huntflow.push``: см. докстринг модуля о повторах."""
    row = await session.get(HuntflowApplicant, row_id)
    if row is None:
        return {"skipped": "row missing"}
    service = HuntflowService(session)
    connection = await session.get(HuntflowConnection, row.connection_id)
    if connection is None or connection.status != HuntflowConnectionStatus.active:
        return await _fail_row(session, row, "Huntflow не подключён или подключение в ошибке")
    candidate = await session.get(Candidate, row.candidate_id)
    interview = await session.get(Interview, row.interview_id) if row.interview_id else None
    if candidate is None or interview is None:
        return await _fail_row(session, row, "Кандидат или интервью не найдены")
    vacancy = await session.get(Vacancy, interview.vacancy_id)
    link = await service._link_for(row.organization_id, interview.vacancy_id)
    if vacancy is None or link is None:
        return await _fail_row(session, row, "Вакансия интервью больше не привязана к Huntflow")
    user = await session.get(User, row.pushed_by_user_id) if row.pushed_by_user_id else None
    actor = await AccountsService(session).get_actor(user) if user and user.is_active else None
    if actor is None or actor.organization_id != row.organization_id:
        return await _fail_row(
            session, row, "Пользователь, запустивший передачу, больше не в организации"
        )

    row.status = HuntflowPushStatus.pushing
    await session.commit()
    account_id: int = connection.account_id  # type: ignore[assignment]
    try:
        client = service.client(connection)
    except ConflictError as error:
        await session.commit()
        return await _fail_row(session, row, str(error))
    try:
        applicant = await _ensure_applicant(client, account_id, candidate, row, vacancy, link)
        share, url = await _ensure_share(session, actor, interview, row)
        status_id = await _target_status(client, account_id, link)
        comment = await build_comment(session, interview, vacancy, url, aware(share.expires_at))
        await client.attach_vacancy(
            account_id,
            applicant.id,
            vacancy_id=link.huntflow_vacancy_id,
            status_id=status_id,
            comment=comment,
        )
    except HuntflowAuthError as error:
        connection.status = HuntflowConnectionStatus.error
        connection.last_error = _truncate(str(error))
        return await _fail_row(session, row, str(error))
    except HuntflowUnavailableError as error:
        # Сеть или 5xx: строка помечается ошибкой, очередь повторит задачу.
        await _fail_row(session, row, str(error))
        raise
    except HuntflowError as error:
        return await _fail_row(session, row, str(error))
    except Exception as error:
        await _fail_row(session, row, f"{type(error).__name__}: {error}")
        raise
    finally:
        await client.aclose()

    row.huntflow_applicant_id = applicant.id
    row.huntflow_vacancy_id = link.huntflow_vacancy_id
    row.huntflow_status_id = status_id
    row.status = HuntflowPushStatus.pushed
    row.last_pushed_at = utcnow()
    row.last_error = None
    if candidate.external_ref is None:
        candidate.external_ref = f"{EXTERNAL_REF_PREFIX}{applicant.id}"
    await session.commit()
    log.info(
        "huntflow.push candidate=%s applicant=%s vacancy=%s status=%s",
        candidate.id,
        applicant.id,
        link.huntflow_vacancy_id,
        status_id,
    )
    return {
        "applicant_id": applicant.id,
        "vacancy_id": link.huntflow_vacancy_id,
        "status_id": status_id,
        "share_id": str(share.id),
    }


async def _fail_row(session: AsyncSession, row: HuntflowApplicant, error: str) -> dict[str, Any]:
    row.status = HuntflowPushStatus.error
    row.last_error = _truncate(error)
    await session.commit()
    return {"error": row.last_error}


def _normalized_name(value: str) -> str:
    return " ".join(sorted(part.lower() for part in value.split() if part))


async def _ensure_applicant(
    client: HuntflowClient,
    account_id: int,
    candidate: Candidate,
    row: HuntflowApplicant,
    vacancy: Vacancy,
    link: HuntflowVacancyLink,
) -> HuntflowApplicantRecord:
    """Найти соискателя по сохранённому id, e-mail или ФИО; иначе создать."""
    known_ids: list[int] = []
    if row.huntflow_applicant_id:
        known_ids.append(row.huntflow_applicant_id)
    if candidate.external_ref and candidate.external_ref.startswith(EXTERNAL_REF_PREFIX):
        with contextlib.suppress(ValueError):
            known_ids.append(int(candidate.external_ref[len(EXTERNAL_REF_PREFIX) :]))
    for applicant_id in known_ids:
        found = await client.get_applicant(account_id, applicant_id)
        if found is not None:
            return found

    email = candidate.email.lower()
    name = _normalized_name(candidate.full_name)
    # Сначала соискатели привязанной вакансии (дёшево), затем весь аккаунт.
    for scope in (link.huntflow_vacancy_id, None):
        records = await client.applicants(account_id, vacancy_id=scope)
        by_email = next((r for r in records if r.email == email), None)
        if by_email is not None:
            return by_email
        if name:
            by_name = next((r for r in records if _normalized_name(r.full_name) == name), None)
            if by_name is not None:
                return by_name

    first, last, middle = split_full_name(candidate.full_name)
    return await client.create_applicant(
        account_id,
        ApplicantCreate(
            first_name=first or candidate.email.split("@", 1)[0],
            last_name=last or "(фамилия не указана)",
            middle_name=middle,
            email=candidate.email,
            phone=candidate.phone,
            position=vacancy.title,
        ),
    )


async def _ensure_share(
    session: AsyncSession, actor: Actor, interview: Interview, row: HuntflowApplicant
) -> tuple[ReportShare, str]:
    """Действующая ссылка на отчёт переиспользуется, иначе выпускается новая на 30 дней."""
    if row.report_share_id and row.report_share_url:
        share = await session.get(ReportShare, row.report_share_id)
        if share is not None and share_status(share) == "active":
            return share, row.report_share_url
    share, token = await ReportService(session).create_share(
        actor,
        interview.id,
        ShareCreate(label=REPORT_SHARE_LABEL, expires_in_days=REPORT_SHARE_DAYS),
    )
    url = share_url(token)
    row.report_share_id = share.id
    row.report_share_url = url
    await session.commit()
    return share, url


async def _target_status(client: HuntflowClient, account_id: int, link: HuntflowVacancyLink) -> int:
    if link.status_id is not None:
        return link.status_id
    statuses = await client.statuses(account_id)
    if not statuses:
        raise HuntflowError("В аккаунте Huntflow нет статусов воронки")
    return statuses[0].id


async def evaluation_summary(session: AsyncSession, interview_id: UUID) -> str | None:
    """«Соответствие …, рекомендация …» — если модуль оценки подключён и заключение готово."""
    try:
        from leonit.evaluation.models import Evaluation  # type: ignore[import-not-found]
    except ImportError:
        return None
    evaluation = await session.scalar(
        select(Evaluation).where(Evaluation.interview_id == interview_id)
    )
    if evaluation is None or getattr(evaluation, "status", None) != "done":
        return None
    parts: list[str] = []
    fit_score = getattr(evaluation, "fit_score", None)
    if fit_score is not None:
        parts.append(f"соответствие {round(fit_score)}/100")
    recommendation = getattr(evaluation, "recommendation", None)
    if recommendation:
        label = RECOMMENDATION_LABELS.get(str(recommendation), str(recommendation))
        parts.append(f"рекомендация ИИ — {label}")
    if not parts:
        return None
    return "Оценка LeonIT: " + ", ".join(parts) + "."


async def build_comment(
    session: AsyncSession,
    interview: Interview,
    vacancy: Vacancy,
    report_url: str,
    expires_at: datetime | None,
) -> str:
    status_label = INTERVIEW_STATUS_LABELS.get(interview.status.value, interview.status.value)
    lines = [f"LeonIT: видеоинтервью по вакансии «{vacancy.title}» — {status_label}."]
    summary = await evaluation_summary(session, interview.id)
    if summary:
        lines.append(summary)
    if interview.decision:
        lines.append(f"Решение: {DECISION_LABELS.get(interview.decision, interview.decision)}.")
    until = f" (действует до {expires_at:%d.%m.%Y})" if expires_at else ""
    lines.append(f"Отчёт для нанимающего менеджера{until}: {report_url}")
    return "\n".join(lines)
