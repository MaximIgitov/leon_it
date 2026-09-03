"""Сервис интеграции HH: подключение, вакансии, отклики и синхронизация.

Методы ``HhService`` работают от имени сотрудника (проверка прав через
``authz``); функции синхронизации внизу — от имени воркера, без актора.
Клиент к HH выбирается по подключению: ``fake`` — фикстуры, ``real`` — HTTP с
расшифрованными токенами и сохранением обновлённых обратно.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.accounts.models import Organization
from leonit.accounts.security import generate_link_token, hash_link_token
from leonit.ai.gateway import get_llm
from leonit.ai.providers.base import LLMProvider
from leonit.candidates.models import Candidate, CandidateSource, Interview
from leonit.core.authz import Actor, authorize
from leonit.core.config import Settings, get_settings
from leonit.core.crypto import SecretBoxError, get_secret_box
from leonit.core.errors import ConflictError, NotFoundError, ValidationFailedError
from leonit.core.logging import get_logger
from leonit.core.time import aware, utcnow
from leonit.hh.client import HhAuthError, HhClient, HhError, HhOAuth, RealHhClient
from leonit.hh.dialog import (
    DEFAULT_DIALOG,
    PLACEHOLDERS,
    SYNTHETIC_EMAIL_DOMAIN,
    DialogRunner,
    dialog_config,
    format_date_ru,
)
from leonit.hh.fake import FakeHhClient
from leonit.hh.models import (
    TERMINAL_DIALOG_STATES,
    HhConnection,
    HhConnectionStatus,
    HhDialogState,
    HhNegotiation,
    HhVacancyLink,
)
from leonit.hh.oauth import make_pkce, make_state, parse_state
from leonit.hh.schemas import (
    DialogMessageOut,
    DialogOut,
    DialogSettings,
    HhConnectionOut,
    HhStatusOut,
    HhVacancyOut,
    NegotiationOut,
    TakeOverIn,
    VacancyLinkOut,
    dialog_preview,
)
from leonit.hh.types import HhResume, HhTokens
from leonit.jobs import service as jobs
from leonit.jobs.models import Job, JobStatus
from leonit.vacancies.models import Vacancy, VacancyStatus

log = get_logger(__name__)

HH_SYNC_JOB = "hh.sync"
PERIODIC_KEY_PREFIX = "hh:sync:periodic:"
_REQUIREMENTS_HEADING_RE = re.compile(
    r"требован|ожида|жд[её]м|нужно|необходим|что важно|плюсом|будет плюс", re.IGNORECASE
)
_HEADING_RE = re.compile(r"^[^.!?]{2,60}:$")


# --------------------------------------------------------------------- клиент


def store_tokens(connection: HhConnection, tokens: HhTokens) -> None:
    box = get_secret_box()
    connection.access_token_enc = box.encrypt(tokens.access_token)
    connection.refresh_token_enc = box.encrypt(tokens.refresh_token)
    connection.expires_at = tokens.expires_at


def build_client(
    session: AsyncSession, connection: HhConnection, settings: Settings | None = None
) -> HhClient:
    """Клиент по подключению; ``fake`` — фикстуры без сети."""
    if connection.mode == "fake":
        return FakeHhClient()
    settings = settings or get_settings()
    box = get_secret_box()
    try:
        tokens = HhTokens(
            access_token=box.decrypt(connection.access_token_enc),
            refresh_token=box.decrypt(connection.refresh_token_enc),
            expires_at=aware(connection.expires_at) or utcnow(),
        )
    except SecretBoxError as error:
        raise HhAuthError("Не удалось расшифровать токены HH — переподключите аккаунт") from error

    async def persist(fresh: HhTokens) -> None:
        store_tokens(connection, fresh)
        await session.commit()

    return RealHhClient(
        settings, tokens, on_tokens=persist, manager_account_id=connection.manager_account_id
    )


def webhook_url(settings: Settings, secret: str) -> str:
    return f"{settings.PUBLIC_URL}{settings.API_PREFIX}/integrations/hh/webhook/{secret}"


def split_description(text: str) -> tuple[str, str]:
    """Описание HH → (описание, требования) по заголовкам вида «Требования:»."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        stripped = line.strip()
        if _HEADING_RE.match(stripped):
            sections.append((stripped, []))
        else:
            sections[-1][1].append(line)
    description: list[str] = []
    requirements: list[str] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if heading is not None and _REQUIREMENTS_HEADING_RE.search(heading):
            requirements.append(f"{heading}\n{body}" if body else heading)
        elif heading is not None:
            description.append(f"{heading}\n{body}" if body else heading)
        elif body:
            description.append(body)
    return "\n\n".join(description).strip(), "\n\n".join(requirements).strip()


# --------------------------------------------------------------------- сервис


class HhService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    # --- подключение ------------------------------------------------------

    async def connection(self, organization_id: UUID) -> HhConnection | None:
        return await self.session.scalar(
            select(HhConnection).where(HhConnection.organization_id == organization_id)
        )

    async def _require_connection(self, actor: Actor) -> HhConnection:
        connection = await self.connection(actor.organization_id)
        if connection is None or connection.status == HhConnectionStatus.disconnected:
            raise NotFoundError("HH.ru не подключён")
        return connection

    def _connection_out(self, connection: HhConnection, *, reveal: bool) -> HhConnectionOut:
        url: str | None = None
        if reveal:
            try:
                url = webhook_url(
                    self.settings, get_secret_box().decrypt(connection.webhook_secret_enc)
                )
            except SecretBoxError:
                url = None
        return HhConnectionOut(
            id=str(connection.id),
            mode=connection.mode,  # type: ignore[arg-type]
            status=connection.status.value,  # type: ignore[arg-type]
            employer_id=connection.employer_id,
            employer_name=connection.employer_name,
            last_error=connection.last_error,
            connected_at=aware(connection.created_at),  # type: ignore[arg-type]
            last_synced_at=aware(connection.last_synced_at),
            webhook_url=url,
        )

    async def status(self, actor: Actor) -> HhStatusOut:
        authorize(actor, "integrations.read")
        connection = await self.connection(actor.organization_id)
        reveal = actor.role.value == "owner"
        return HhStatusOut(
            mode=self.settings.effective_hh_mode,
            configured=bool(self.settings.HH_CLIENT_ID and self.settings.HH_CLIENT_SECRET),
            sync_interval_minutes=self.settings.HH_SYNC_INTERVAL_MINUTES,
            connection=(
                self._connection_out(connection, reveal=reveal)
                if connection is not None and connection.status != HhConnectionStatus.disconnected
                else None
            ),
        )

    async def oauth_start(self, actor: Actor) -> str:
        authorize(actor, "integrations.manage")
        if self.settings.effective_hh_mode != "real":
            raise ConflictError(
                "Ключи HH_CLIENT_ID/HH_CLIENT_SECRET не заданы — доступен только демо-аккаунт"
            )
        verifier, challenge = make_pkce()
        state = make_state(
            self.settings,
            get_secret_box(),
            organization_id=actor.organization_id,
            user_id=actor.user.id,
            code_verifier=verifier,
        )
        return HhOAuth(self.settings).authorize_url(state=state, code_challenge=challenge)

    async def oauth_callback(self, *, code: str, state: str) -> HhConnection:
        """Обменять код на токены, узнать работодателя и сохранить подключение."""
        parsed = parse_state(self.settings, get_secret_box(), state)
        if parsed is None:
            raise ValidationFailedError("Состояние OAuth недействительно или устарело")
        organization = await self.session.get(Organization, parsed.organization_id)
        if organization is None:
            raise ValidationFailedError("Организация не найдена")
        oauth = HhOAuth(self.settings)
        tokens = await oauth.exchange_code(code, code_verifier=parsed.code_verifier)
        async with RealHhClient(self.settings, tokens) as client:
            employer = await client.me()
            tokens = client.tokens
        if not employer.id:
            raise ValidationFailedError(
                "Аккаунт HH не привязан к работодателю — нужен аккаунт менеджера компании"
            )
        connection = await self._upsert_connection(
            organization.id,
            mode="real",
            employer_id=employer.id,
            employer_name=employer.name,
            hh_user_id=employer.user_id,
            manager_account_id=employer.manager_account_id,
            connected_by=parsed.user_id,
        )
        store_tokens(connection, tokens)
        await self.session.commit()
        return connection

    async def connect_demo(self, actor: Actor) -> HhConnection:
        authorize(actor, "integrations.manage")
        if self.settings.effective_hh_mode != "fake":
            raise ConflictError("Демо-режим недоступен: заданы ключи HH — подключите аккаунт")
        employer = await FakeHhClient().me()
        connection = await self._upsert_connection(
            actor.organization_id,
            mode="fake",
            employer_id=employer.id,
            employer_name=employer.name,
            hh_user_id=employer.user_id,
            manager_account_id=employer.manager_account_id,
            connected_by=actor.user.id,
        )
        store_tokens(
            connection,
            HhTokens(
                access_token="fake-access-token",
                refresh_token="fake-refresh-token",
                expires_at=utcnow() + timedelta(days=14),
            ),
        )
        await self.session.commit()
        return connection

    async def _upsert_connection(
        self,
        organization_id: UUID,
        *,
        mode: str,
        employer_id: str,
        employer_name: str,
        hh_user_id: str,
        manager_account_id: str | None,
        connected_by: UUID | None,
    ) -> HhConnection:
        connection = await self.connection(organization_id)
        if connection is None:
            secret = generate_link_token()
            connection = HhConnection(
                organization_id=organization_id,
                webhook_secret_hash=hash_link_token(secret),
                webhook_secret_enc=get_secret_box().encrypt(secret),
            )
            self.session.add(connection)
        connection.mode = mode
        connection.employer_id = employer_id
        connection.employer_name = employer_name
        connection.hh_user_id = hh_user_id
        connection.manager_account_id = manager_account_id
        connection.connected_by_user_id = connected_by
        connection.status = HhConnectionStatus.connected
        connection.last_error = ""
        await self.session.flush()
        return connection

    async def disconnect(self, actor: Actor) -> None:
        authorize(actor, "integrations.manage")
        connection = await self._require_connection(actor)
        # Токены стираем сразу; привязки и история диалогов остаются в карточках.
        connection.access_token_enc = ""
        connection.refresh_token_enc = ""
        connection.expires_at = None
        connection.status = HhConnectionStatus.disconnected
        connection.last_error = ""
        await self.session.commit()

    # --- вакансии ---------------------------------------------------------

    async def _links(self, organization_id: UUID) -> list[HhVacancyLink]:
        return list(
            (
                await self.session.scalars(
                    select(HhVacancyLink)
                    .where(HhVacancyLink.organization_id == organization_id)
                    .order_by(HhVacancyLink.created_at.desc())
                )
            ).all()
        )

    async def _link_outs(self, links: list[HhVacancyLink]) -> dict[UUID, VacancyLinkOut]:
        if not links:
            return {}
        vacancy_ids = {link.vacancy_id for link in links}
        rows = await self.session.execute(
            select(Vacancy.id, Vacancy.title, Vacancy.status).where(Vacancy.id.in_(vacancy_ids))
        )
        vacancies = {row.id: (row.title, row.status) for row in rows.all()}
        counts = dict(
            (
                await self.session.execute(
                    select(HhNegotiation.vacancy_link_id, func.count())
                    .where(HhNegotiation.vacancy_link_id.in_([link.id for link in links]))
                    .group_by(HhNegotiation.vacancy_link_id)
                )
            ).all()
        )
        result: dict[UUID, VacancyLinkOut] = {}
        for link in links:
            title, status = vacancies.get(link.vacancy_id, ("", VacancyStatus.draft))
            config = dialog_config(link.dialog)
            result[link.id] = VacancyLinkOut(
                id=str(link.id),
                hh_vacancy_id=link.hh_vacancy_id,
                hh_title=link.hh_title,
                hh_url=link.hh_url,
                vacancy_id=str(link.vacancy_id),
                vacancy_title=title,
                vacancy_status=status.value,
                dialog_enabled=config.enabled,
                max_days=config.max_days,
                negotiation_count=int(counts.get(link.id, 0)),
                created_at=aware(link.created_at),  # type: ignore[arg-type]
            )
        return result

    async def list_links(self, actor: Actor) -> list[VacancyLinkOut]:
        authorize(actor, "integrations.read")
        links = await self._links(actor.organization_id)
        outs = await self._link_outs(links)
        return [outs[link.id] for link in links]

    async def list_hh_vacancies(self, actor: Actor) -> list[HhVacancyOut]:
        authorize(actor, "integrations.read")
        connection = await self._require_connection(actor)
        client = build_client(self.session, connection, self.settings)
        try:
            items = await client.employer_vacancies(connection.employer_id)
        except HhAuthError as error:
            await self._mark_auth_error(connection, error)
            raise
        finally:
            await _close(client)
        links = await self._links(actor.organization_id)
        outs = await self._link_outs(links)
        by_hh_id = {link.hh_vacancy_id: outs[link.id] for link in links}
        return [
            HhVacancyOut(
                id=item.id,
                name=item.name,
                url=item.url,
                area=item.area,
                salary=item.salary,
                published_at=item.published_at,
                key_skills=item.key_skills,
                link=by_hh_id.get(item.id),
            )
            for item in items
        ]

    async def _existing_link(
        self, connection: HhConnection, hh_vacancy_id: str
    ) -> HhVacancyLink | None:
        return await self.session.scalar(
            select(HhVacancyLink).where(
                HhVacancyLink.connection_id == connection.id,
                HhVacancyLink.hh_vacancy_id == hh_vacancy_id,
            )
        )

    async def import_vacancy(self, actor: Actor, hh_vacancy_id: str) -> VacancyLinkOut:
        """Создать локальный черновик вакансии из HH и привязать его."""
        authorize(actor, "integrations.operate")
        authorize(actor, "vacancy.write")
        connection = await self._require_connection(actor)
        if await self._existing_link(connection, hh_vacancy_id) is not None:
            raise ConflictError("Эта вакансия HH уже привязана к локальной")
        client = build_client(self.session, connection, self.settings)
        try:
            hh = await client.vacancy(hh_vacancy_id)
        except HhAuthError as error:
            await self._mark_auth_error(connection, error)
            raise
        finally:
            await _close(client)
        description, requirements = split_description(hh.description_text)
        vacancy = Vacancy(
            organization_id=actor.organization_id,
            created_by_user_id=actor.user.id,
            title=hh.name[:255] or f"Вакансия HH {hh.id}",
            description=description[:20000],
            requirements=requirements[:20000],
            skills=[skill[:64] for skill in hh.key_skills[:50]],
        )
        self.session.add(vacancy)
        await self.session.flush()
        link = await self._create_link(actor, connection, hh_vacancy_id, vacancy, hh.name, hh.url)
        await self.session.commit()
        return (await self._link_outs([link]))[link.id]

    async def link_vacancy(
        self, actor: Actor, hh_vacancy_id: str, vacancy_id: UUID
    ) -> VacancyLinkOut:
        authorize(actor, "integrations.operate")
        authorize(actor, "vacancy.write", vacancy_id=vacancy_id)
        connection = await self._require_connection(actor)
        vacancy = await self.session.scalar(
            select(Vacancy).where(
                Vacancy.id == vacancy_id, Vacancy.organization_id == actor.organization_id
            )
        )
        if vacancy is None:
            raise NotFoundError("Вакансия не найдена")
        client = build_client(self.session, connection, self.settings)
        try:
            hh = await client.vacancy(hh_vacancy_id)
        except HhAuthError as error:
            await self._mark_auth_error(connection, error)
            raise
        finally:
            await _close(client)
        link = await self._existing_link(connection, hh_vacancy_id)
        if link is None:
            link = await self._create_link(
                actor, connection, hh_vacancy_id, vacancy, hh.name, hh.url
            )
        else:
            link.vacancy_id = vacancy.id
            link.hh_title = hh.name[:255]
            link.hh_url = hh.url[:512]
        await self.session.commit()
        return (await self._link_outs([link]))[link.id]

    async def _create_link(
        self,
        actor: Actor,
        connection: HhConnection,
        hh_vacancy_id: str,
        vacancy: Vacancy,
        title: str,
        url: str,
    ) -> HhVacancyLink:
        link = HhVacancyLink(
            organization_id=actor.organization_id,
            connection_id=connection.id,
            vacancy_id=vacancy.id,
            hh_vacancy_id=hh_vacancy_id,
            hh_title=title[:255],
            hh_url=url[:512],
            dialog=dict(DEFAULT_DIALOG),
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def _get_link(self, actor: Actor, link_id: UUID) -> HhVacancyLink:
        link = await self.session.scalar(
            select(HhVacancyLink).where(
                HhVacancyLink.id == link_id,
                HhVacancyLink.organization_id == actor.organization_id,
            )
        )
        if link is None:
            raise NotFoundError("Привязка вакансии не найдена")
        return link

    async def _dialog_out(self, link: HhVacancyLink) -> DialogOut:
        vacancy = await self.session.get(Vacancy, link.vacancy_id)
        config = dialog_config(link.dialog)
        settings = DialogSettings(**config.as_dict())
        values = {
            "candidate_name": "Анна",
            "vacancy_title": vacancy.title if vacancy else link.hh_title,
            "days": config.max_days,
            "link": f"{self.settings.PUBLIC_URL}/i/<токен>",
            "date": format_date_ru((utcnow() + timedelta(days=3)).date()),
        }
        return DialogOut(
            **settings.model_dump(),
            placeholders=list(PLACEHOLDERS),
            preview=dialog_preview(values, settings),
        )

    async def get_dialog(self, actor: Actor, link_id: UUID) -> DialogOut:
        authorize(actor, "integrations.read")
        return await self._dialog_out(await self._get_link(actor, link_id))

    async def update_dialog(
        self, actor: Actor, link_id: UUID, payload: DialogSettings
    ) -> DialogOut:
        authorize(actor, "integrations.operate")
        link = await self._get_link(actor, link_id)
        link.dialog = payload.model_dump()
        await self.session.commit()
        return await self._dialog_out(link)

    # --- отклики -------------------------------------------------------------

    async def list_negotiations(
        self,
        actor: Actor,
        *,
        candidate_id: UUID | None = None,
        link_id: UUID | None = None,
    ) -> list[NegotiationOut]:
        authorize(actor, "integrations.read")
        stmt = (
            select(HhNegotiation, Candidate, HhVacancyLink, Vacancy.title, Interview.status)
            .join(Candidate, Candidate.id == HhNegotiation.candidate_id)
            .join(HhVacancyLink, HhVacancyLink.id == HhNegotiation.vacancy_link_id)
            .join(Vacancy, Vacancy.id == HhVacancyLink.vacancy_id)
            .outerjoin(Interview, Interview.id == HhNegotiation.interview_id)
            .where(HhNegotiation.organization_id == actor.organization_id)
            .order_by(HhNegotiation.created_at.desc())
        )
        if candidate_id is not None:
            stmt = stmt.where(HhNegotiation.candidate_id == candidate_id)
        if link_id is not None:
            stmt = stmt.where(HhNegotiation.vacancy_link_id == link_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            negotiation_out(negotiation, candidate, link, title, status)
            for negotiation, candidate, link, title, status in rows
        ]

    async def _negotiation(self, actor: Actor, negotiation_id: UUID) -> HhNegotiation:
        negotiation = await self.session.scalar(
            select(HhNegotiation).where(
                HhNegotiation.id == negotiation_id,
                HhNegotiation.organization_id == actor.organization_id,
            )
        )
        if negotiation is None:
            raise NotFoundError("Отклик не найден")
        return negotiation

    async def request_sync(self, actor: Actor) -> Job:
        authorize(actor, "integrations.operate")
        await self._require_connection(actor)
        job = await enqueue_org_sync(self.session, actor.organization_id, reason="manual")
        await self.session.commit()
        return job

    async def take_over(
        self, actor: Actor, negotiation_id: UUID, payload: TakeOverIn
    ) -> NegotiationOut:
        """Рекрутер берёт отклик в работу: ссылка на интервью уходит в чат сразу."""
        authorize(actor, "integrations.operate")
        negotiation = await self._negotiation(actor, negotiation_id)
        if negotiation.state in (HhDialogState.link_sent, *TERMINAL_DIALOG_STATES):
            raise ConflictError("Ссылка уже отправлена или диалог завершён")
        link = await self.session.get(HhVacancyLink, negotiation.vacancy_link_id)
        vacancy = await self.session.scalar(
            select(Vacancy)
            .where(Vacancy.id == link.vacancy_id)
            .options(selectinload(Vacancy.questions))
        )
        candidate = await self.session.get(Candidate, negotiation.candidate_id)
        assert link is not None and vacancy is not None and candidate is not None
        authorize(actor, "candidate.write", vacancy_id=vacancy.id)
        if vacancy.status != VacancyStatus.published:
            raise ValidationFailedError("Сначала опубликуйте вакансию — иначе ссылка не откроется")
        connection = await self._require_connection(actor)
        client = build_client(self.session, connection, self.settings)
        try:
            runner = DialogRunner(self.session, client, llm=None)
            await runner.pull(negotiation)
            days = payload.days or vacancy.invitation_days
            await runner.send_link(
                negotiation,
                link,
                vacancy,
                candidate,
                actor.organization,
                chosen=None,
                expires_at=utcnow() + timedelta(days=days),
                invited_by_user_id=actor.user.id,
            )
        except HhAuthError as error:
            await self._mark_auth_error(connection, error)
            raise
        finally:
            await _close(client)
        negotiation.last_error = ""
        await self.session.commit()
        return await self._one_out(actor, negotiation.id)

    async def _one_out(self, actor: Actor, negotiation_id: UUID) -> NegotiationOut:
        for item in await self.list_negotiations(actor):
            if item.id == str(negotiation_id):
                return item
        raise NotFoundError("Отклик не найден")

    async def _mark_auth_error(self, connection: HhConnection, error: Exception) -> None:
        connection.status = HhConnectionStatus.error
        connection.last_error = str(error)[:500]
        await self.session.commit()

    # --- вебхук -------------------------------------------------------------

    async def handle_webhook(self, secret: str) -> Job:
        connection = await self.session.scalar(
            select(HhConnection).where(HhConnection.webhook_secret_hash == hash_link_token(secret))
        )
        if connection is None or connection.status == HhConnectionStatus.disconnected:
            raise NotFoundError("Not found")
        job = await enqueue_org_sync(self.session, connection.organization_id, reason="webhook")
        await self.session.commit()
        return job


def negotiation_out(
    negotiation: HhNegotiation,
    candidate: Candidate,
    link: HhVacancyLink,
    vacancy_title: str,
    interview_status: Any,
) -> NegotiationOut:
    messages = []
    for entry in negotiation.messages:
        at: datetime | None = None
        try:
            at = datetime.fromisoformat(str(entry.get("at"))) if entry.get("at") else None
        except ValueError:
            at = None
        messages.append(
            DialogMessageOut(
                role=entry.get("role") or "bot",
                text=str(entry.get("text") or ""),
                at=at,
                hh_message_id=entry.get("hh_message_id"),
                step=entry.get("step"),
            )
        )
    return NegotiationOut(
        id=str(negotiation.id),
        negotiation_id=negotiation.negotiation_id,
        state=negotiation.state.value,  # type: ignore[arg-type]
        chosen_date=negotiation.chosen_date,
        candidate_id=str(candidate.id),
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        vacancy_id=str(link.vacancy_id),
        vacancy_title=vacancy_title,
        vacancy_link_id=str(link.id),
        hh_vacancy_id=link.hh_vacancy_id,
        interview_id=str(negotiation.interview_id) if negotiation.interview_id else None,
        interview_status=getattr(interview_status, "value", interview_status),
        messages=messages,
        last_error=negotiation.last_error,
        last_synced_at=aware(negotiation.last_synced_at),
        created_at=aware(negotiation.created_at),  # type: ignore[arg-type]
    )


async def _close(client: HhClient) -> None:
    close = getattr(client, "aclose", None)
    if close is not None:
        await close()


# ------------------------------------------------------------- синхронизация


async def enqueue_org_sync(session: AsyncSession, organization_id: UUID, *, reason: str) -> Job:
    """Внеочередная синхронизация организации; активная задача не дублируется."""
    return await jobs.enqueue(
        session,
        HH_SYNC_JOB,
        {"organization_id": str(organization_id), "reason": reason},
        dedupe_key=f"hh:sync:org:{organization_id}",
        max_attempts=3,
    )


async def schedule_periodic_sync(session: AsyncSession, *, run_after: datetime) -> Job:
    key = f"{PERIODIC_KEY_PREFIX}{run_after.strftime('%Y%m%d%H%M')}"
    return await jobs.enqueue(
        session,
        HH_SYNC_JOB,
        {"periodic": True},
        run_after=run_after,
        dedupe_key=key,
        max_attempts=3,
    )


async def ensure_periodic_sync(session: AsyncSession) -> Job:
    """Гарантировать одну активную периодическую задачу (страховка на старте и тике)."""
    active = await session.scalar(
        select(Job)
        .where(
            Job.kind == HH_SYNC_JOB,
            Job.dedupe_key.like(f"{PERIODIC_KEY_PREFIX}%"),
            Job.status.in_([JobStatus.queued, JobStatus.running]),
        )
        .limit(1)
    )
    if active is not None:
        return active
    return await schedule_periodic_sync(session, run_after=utcnow())


async def get_or_create_candidate(
    session: AsyncSession, organization_id: UUID, resume: HhResume
) -> tuple[Candidate, bool]:
    """Кандидат по e-mail из резюме; без e-mail — синтетический адрес по id резюме."""
    email = (resume.email or f"hh-{resume.id}@{SYNTHETIC_EMAIL_DOMAIN}").lower()
    existing = await session.scalar(
        select(Candidate).where(
            Candidate.organization_id == organization_id, Candidate.email == email
        )
    )
    text = resume.as_text()
    if existing is not None:
        if not existing.resume_text and text:
            existing.resume_text = text
        if not existing.phone and resume.phone:
            existing.phone = resume.phone
        if not existing.external_ref:
            existing.external_ref = f"hh:{resume.id}"
        return existing, False
    candidate = Candidate(
        organization_id=organization_id,
        full_name=(resume.full_name or email.split("@", 1)[0])[:255],
        email=email,
        phone=resume.phone,
        source=CandidateSource.hh,
        notes=f"Резюме HH: {resume.title}" if resume.title else "",
        resume_text=text or None,
        external_ref=f"hh:{resume.id}",
    )
    session.add(candidate)
    await session.flush()
    return candidate, True


async def sync_connection(
    session: AsyncSession,
    connection: HhConnection,
    client: HhClient,
    *,
    llm: LLMProvider | None,
) -> dict[str, int]:
    """Новые отклики → кандидаты и приветствие; новые сообщения → шаги диалога."""
    stats = {"negotiations_new": 0, "candidates_new": 0, "messages_in": 0, "errors": 0}
    organization = await session.get(Organization, connection.organization_id)
    assert organization is not None
    links = list(
        (
            await session.scalars(
                select(HhVacancyLink)
                .where(HhVacancyLink.connection_id == connection.id)
                .options(selectinload(HhVacancyLink.negotiations))
            )
        ).all()
    )
    runner = DialogRunner(session, client, llm=llm)
    now = utcnow()
    for link in links:
        vacancy = await _load_vacancy(session, link.vacancy_id)
        if vacancy is None:
            continue
        known = {item.negotiation_id for item in link.negotiations}
        for info in await client.negotiations(link.hh_vacancy_id):
            if not info.id or info.id in known:
                continue
            resume = await client.resume(info.resume_id, negotiation_id=info.id)
            candidate, created = await get_or_create_candidate(session, organization.id, resume)
            negotiation = HhNegotiation(
                organization_id=organization.id,
                connection_id=connection.id,
                vacancy_link_id=link.id,
                negotiation_id=info.id,
                chat_id=info.chat_id,
                resume_id=info.resume_id,
                candidate_id=candidate.id,
                state=HhDialogState.new,
            )
            session.add(negotiation)
            await session.flush()
            link.negotiations.append(negotiation)
            known.add(info.id)
            stats["negotiations_new"] += 1
            stats["candidates_new"] += int(created)
        link.last_synced_at = now
        await session.commit()

        config = dialog_config(link.dialog)
        dialog_ready = config.enabled and vacancy.status == VacancyStatus.published
        for negotiation in list(link.negotiations):
            # После rollback (ошибка предыдущего отклика) объекты протухли; в
            # асинхронной сессии их нужно перечитать явно, а не лениво.
            if inspect(negotiation).expired:
                await session.refresh(negotiation)
            if negotiation.state in TERMINAL_DIALOG_STATES:
                continue
            candidate = await session.get(Candidate, negotiation.candidate_id)
            if candidate is None:
                continue
            try:
                fresh = await runner.pull(negotiation)
                stats["messages_in"] += len(fresh)
                if negotiation.state == HhDialogState.new:
                    if dialog_ready:
                        await runner.start(negotiation, link, vacancy, candidate)
                elif negotiation.state in (
                    HhDialogState.greeting_sent,
                    HhDialogState.awaiting_slot,
                ):
                    if dialog_ready:
                        await runner.advance(
                            negotiation, link, vacancy, candidate, organization, fresh
                        )
                elif negotiation.state == HhDialogState.link_sent:
                    await runner.refresh_done(negotiation)
                negotiation.last_error = ""
            except HhAuthError:
                await session.rollback()
                raise
            except Exception as error:  # один отклик не должен ронять остальные
                await session.rollback()
                log.exception("hh.sync negotiation %s failed", negotiation.negotiation_id)
                await session.refresh(negotiation)
                negotiation.last_error = str(error)[:500]
                stats["errors"] += 1
                vacancy = await _load_vacancy(session, link.vacancy_id) or vacancy
                await session.refresh(link)
                await session.refresh(organization)
            negotiation.last_synced_at = now
            await session.commit()
    if inspect(connection).expired:
        await session.refresh(connection)
    connection.last_synced_at = now
    await session.commit()
    return stats


async def _load_vacancy(session: AsyncSession, vacancy_id: UUID) -> Vacancy | None:
    return await session.scalar(
        select(Vacancy)
        .where(Vacancy.id == vacancy_id)
        .options(selectinload(Vacancy.questions))
        .execution_options(populate_existing=True)
    )


async def sync_organizations(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    client_factory: Callable[[AsyncSession, HhConnection], HhClient] | None = None,
    llm: LLMProvider | None = None,
) -> dict[str, Any]:
    """Синхронизировать все активные подключения (или одно — организации)."""
    stmt = select(HhConnection).where(HhConnection.status != HhConnectionStatus.disconnected)
    if organization_id is not None:
        stmt = stmt.where(HhConnection.organization_id == organization_id)
    connections = list((await session.scalars(stmt)).all())
    totals: dict[str, Any] = {"connections": len(connections), "failed": 0}
    if llm is None:
        llm = get_llm("assistant")
    for connection in connections:
        client = (client_factory or build_client)(session, connection)
        try:
            stats = await sync_connection(session, connection, client, llm=llm)
            connection.status = HhConnectionStatus.connected
            connection.last_error = ""
            await session.commit()
            for key, value in stats.items():
                totals[key] = totals.get(key, 0) + value
        except HhAuthError as error:
            connection.status = HhConnectionStatus.error
            connection.last_error = str(error)[:500]
            await session.commit()
            totals["failed"] += 1
            log.warning("hh.sync auth error for org %s: %s", connection.organization_id, error)
        except HhError as error:
            connection.last_error = str(error)[:500]
            await session.commit()
            totals["failed"] += 1
            log.warning("hh.sync upstream error for org %s: %s", connection.organization_id, error)
        finally:
            await _close(client)
    return totals
