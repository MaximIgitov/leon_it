from __future__ import annotations

import math
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.accounts.models import Organization
from leonit.accounts.security import generate_link_token, hash_link_token
from leonit.candidates.models import (
    TRANSITIONS,
    Candidate,
    CandidateSource,
    ConsentRecord,
    Interview,
    InterviewStatus,
)
from leonit.candidates.schemas import (
    CandidateBulkCreate,
    CandidateCreate,
    CandidateUpdate,
    ConsentSubmit,
    InviteRequest,
)
from leonit.core.authz import Actor, authorize, visible_vacancy_ids
from leonit.core.config import get_settings
from leonit.core.errors import ConflictError, NotFoundError, ValidationFailedError
from leonit.core.time import aware, utcnow
from leonit.legal.service import consent_documents, load_document
from leonit.notifications.service import queue_email
from leonit.notifications.templates import invitation_email
from leonit.vacancies.models import Vacancy, VacancyStatus


def interview_link(token: str) -> str:
    return f"{get_settings().PUBLIC_URL}/i/{token}"


def estimated_minutes(vacancy: Vacancy) -> int:
    per_question = vacancy.prep_seconds + vacancy.max_answer_seconds
    total_s = len(vacancy.questions) * per_question
    # Тренировочный вопрос и проверка устройств — плюс пара минут.
    return max(3, math.ceil(total_s / 60) + 3)


def transition(interview: Interview, new_status: InterviewStatus) -> None:
    allowed = TRANSITIONS[interview.status]
    if new_status not in allowed:
        raise ConflictError(
            f"Недопустимый переход статуса интервью: {interview.status.value} → {new_status.value}"
        )
    now = utcnow()
    interview.status = new_status
    stamps = {
        InterviewStatus.opened: "opened_at",
        InterviewStatus.consented: "consented_at",
        InterviewStatus.in_progress: "started_at",
        InterviewStatus.completed: "completed_at",
        InterviewStatus.evaluated: "evaluated_at",
        InterviewStatus.advanced: "decided_at",
        InterviewStatus.rejected: "decided_at",
        InterviewStatus.cancelled: "cancelled_at",
    }
    field = stamps.get(new_status)
    if field:
        setattr(interview, field, now)


class CandidateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, actor: Actor, *, search: str | None = None) -> list[Candidate]:
        authorize(actor, "candidate.read")
        stmt = (
            select(Candidate)
            .where(Candidate.organization_id == actor.organization_id)
            .options(selectinload(Candidate.interviews))
            .order_by(Candidate.created_at.desc())
        )
        candidates = list((await self.session.scalars(stmt)).all())
        if search:
            # Регистр приводим в Python: lower()/LIKE в SQLite не знают кириллицы,
            # а кандидатов в организации немного.
            needle = search.strip().lower()
            candidates = [
                c for c in candidates if needle in c.full_name.lower() or needle in c.email.lower()
            ]
        visible = visible_vacancy_ids(actor)
        if visible is not None:
            # Нанимающий менеджер видит только кандидатов допущенных вакансий.
            allowed = {UUID(item) for item in visible}
            candidates = [
                c for c in candidates if any(i.vacancy_id in allowed for i in c.interviews)
            ]
        return candidates

    async def get(self, actor: Actor, candidate_id: UUID) -> Candidate:
        candidate = await self.session.scalar(
            select(Candidate)
            .where(
                Candidate.id == candidate_id,
                Candidate.organization_id == actor.organization_id,
            )
            .options(selectinload(Candidate.interviews))
            .execution_options(populate_existing=True)
        )
        if candidate is None:
            raise NotFoundError("Кандидат не найден")
        visible = visible_vacancy_ids(actor)
        if visible is not None:
            allowed = {UUID(item) for item in visible}
            if not any(i.vacancy_id in allowed for i in candidate.interviews):
                raise NotFoundError("Кандидат не найден")
        authorize(actor, "candidate.read")
        return candidate

    async def get_or_create(
        self,
        actor: Actor,
        *,
        full_name: str,
        email: str,
        source: CandidateSource = CandidateSource.manual,
        phone: str | None = None,
        notes: str = "",
        external_ref: str | None = None,
    ) -> tuple[Candidate, bool]:
        authorize(actor, "candidate.write")
        email = email.lower()
        existing = await self.session.scalar(
            select(Candidate).where(
                Candidate.organization_id == actor.organization_id, Candidate.email == email
            )
        )
        if existing is not None:
            return existing, False
        candidate = Candidate(
            organization_id=actor.organization_id,
            full_name=full_name.strip(),
            email=email,
            phone=phone,
            notes=notes,
            source=source,
            external_ref=external_ref,
            created_by_user_id=actor.user.id,
        )
        self.session.add(candidate)
        await self.session.flush()
        return candidate, True

    async def create(
        self,
        actor: Actor,
        payload: CandidateCreate,
        *,
        source: CandidateSource = CandidateSource.manual,
    ) -> Candidate:
        candidate, created = await self.get_or_create(
            actor,
            full_name=payload.full_name,
            email=payload.email,
            source=source,
            phone=payload.phone,
            notes=payload.notes,
            external_ref=payload.external_ref,
        )
        if not created:
            raise ConflictError("Кандидат с таким e-mail уже есть")
        await self.session.commit()
        return await self.get(actor, candidate.id)

    async def bulk_create(
        self, actor: Actor, payload: CandidateBulkCreate
    ) -> tuple[list[Candidate], list[Candidate], int]:
        authorize(actor, "candidate.write")
        rows = payload.parse()
        lines = [line for line in payload.text.splitlines() if line.strip()]
        created: list[Candidate] = []
        existing: list[Candidate] = []
        seen: set[str] = set()
        for name, email in rows:
            if email in seen:
                continue
            seen.add(email)
            candidate, is_new = await self.get_or_create(
                actor, full_name=name, email=email, source=CandidateSource.bulk
            )
            (created if is_new else existing).append(candidate)
        await self.session.commit()
        return created, existing, len(lines) - len(rows)

    async def update(self, actor: Actor, candidate_id: UUID, payload: CandidateUpdate) -> Candidate:
        authorize(actor, "candidate.write")
        candidate = await self.get(actor, candidate_id)
        for field in ("full_name", "phone", "notes"):
            if field in payload.model_fields_set:
                setattr(candidate, field, getattr(payload, field))
        await self.session.commit()
        return await self.get(actor, candidate.id)


class InterviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _vacancy(self, actor: Actor, vacancy_id: UUID) -> Vacancy:
        vacancy = await self.session.scalar(
            select(Vacancy)
            .where(Vacancy.id == vacancy_id, Vacancy.organization_id == actor.organization_id)
            .options(selectinload(Vacancy.questions))
        )
        if vacancy is None:
            raise NotFoundError("Вакансия не найдена")
        return vacancy

    async def invite(
        self,
        actor: Actor,
        payload: InviteRequest,
        *,
        source: CandidateSource = CandidateSource.manual,
    ) -> tuple[Interview, str]:
        vacancy = await self._vacancy(actor, UUID(payload.vacancy_id))
        authorize(actor, "candidate.write", vacancy_id=vacancy.id)
        if vacancy.status != VacancyStatus.published:
            raise ValidationFailedError("Приглашать можно только по опубликованной вакансии")
        candidates = CandidateService(self.session)
        if payload.candidate_id:
            candidate = await candidates.get(actor, UUID(payload.candidate_id))
        elif payload.email and payload.full_name:
            candidate, _ = await candidates.get_or_create(
                actor, full_name=payload.full_name, email=payload.email, source=source
            )
        else:
            raise ValidationFailedError("Укажите кандидата или имя и e-mail нового")

        active = await self.session.scalar(
            select(Interview).where(
                Interview.candidate_id == candidate.id,
                Interview.vacancy_id == vacancy.id,
                Interview.status.notin_(
                    [InterviewStatus.cancelled, InterviewStatus.expired, InterviewStatus.rejected]
                ),
            )
        )
        if active is not None:
            raise ConflictError("У кандидата уже есть активное интервью по этой вакансии")

        token = generate_link_token()
        interview = Interview(
            organization_id=actor.organization_id,
            vacancy_id=vacancy.id,
            candidate_id=candidate.id,
            token_hash=hash_link_token(token),
            invited_by_user_id=actor.user.id,
            expires_at=utcnow() + timedelta(days=vacancy.invitation_days),
        )
        self.session.add(interview)
        await self.session.flush()
        if payload.send_email:
            await self._queue_invitation(actor.organization, vacancy, candidate, interview, token)
        await self.session.commit()
        return await self.get(actor, interview.id), token

    async def _queue_invitation(
        self,
        organization: Organization,
        vacancy: Vacancy,
        candidate: Candidate,
        interview: Interview,
        token: str,
    ) -> None:
        subject, body = invitation_email(
            candidate_name=candidate.full_name,
            organization_name=organization.name,
            vacancy_title=vacancy.title,
            link=interview_link(token),
            expires_at=aware(interview.expires_at),  # type: ignore[arg-type]
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

    async def get(self, actor: Actor, interview_id: UUID) -> Interview:
        interview = await self.session.scalar(
            select(Interview)
            .where(
                Interview.id == interview_id,
                Interview.organization_id == actor.organization_id,
            )
            .options(selectinload(Interview.candidate))
            .execution_options(populate_existing=True)
        )
        if interview is None:
            raise NotFoundError("Интервью не найдено")
        authorize(actor, "interview.read", vacancy_id=interview.vacancy_id)
        return interview

    async def list(
        self,
        actor: Actor,
        *,
        vacancy_id: UUID | None = None,
        candidate_id: UUID | None = None,
    ) -> list[Interview]:
        authorize(actor, "interview.read")
        stmt = (
            select(Interview)
            .where(Interview.organization_id == actor.organization_id)
            .options(selectinload(Interview.candidate))
            .order_by(Interview.invited_at.desc())
        )
        if vacancy_id is not None:
            authorize(actor, "interview.read", vacancy_id=vacancy_id)
            stmt = stmt.where(Interview.vacancy_id == vacancy_id)
        if candidate_id is not None:
            stmt = stmt.where(Interview.candidate_id == candidate_id)
        visible = visible_vacancy_ids(actor)
        if visible is not None:
            if not visible:
                return []
            stmt = stmt.where(Interview.vacancy_id.in_([UUID(item) for item in visible]))
        return list((await self.session.scalars(stmt)).all())

    async def resend(self, actor: Actor, interview_id: UUID) -> tuple[Interview, str]:
        interview = await self.get(actor, interview_id)
        authorize(actor, "candidate.write", vacancy_id=interview.vacancy_id)
        if interview.status not in (
            InterviewStatus.invited,
            InterviewStatus.opened,
            InterviewStatus.consented,
            InterviewStatus.in_progress,
            InterviewStatus.expired,
        ):
            raise ConflictError("Ссылку можно переслать только по незавершённому интервью")
        vacancy = await self._vacancy(actor, interview.vacancy_id)
        token = generate_link_token()
        interview.token_hash = hash_link_token(token)
        interview.expires_at = utcnow() + timedelta(days=vacancy.invitation_days)
        if interview.status == InterviewStatus.expired:
            transition(interview, InterviewStatus.invited)
        await self._queue_invitation(
            actor.organization, vacancy, interview.candidate, interview, token
        )
        await self.session.commit()
        return await self.get(actor, interview.id), token

    async def cancel(self, actor: Actor, interview_id: UUID) -> Interview:
        interview = await self.get(actor, interview_id)
        authorize(actor, "candidate.write", vacancy_id=interview.vacancy_id)
        transition(interview, InterviewStatus.cancelled)
        await self.session.commit()
        return await self.get(actor, interview.id)

    # ---------------------------------------------------------------- public

    async def by_token(self, token: str) -> tuple[Interview, Vacancy, Organization]:
        interview = await self.session.scalar(
            select(Interview)
            .where(Interview.token_hash == hash_link_token(token))
            .options(selectinload(Interview.candidate))
        )
        if interview is None:
            raise NotFoundError("Ссылка на интервью недействительна")
        vacancy = await self.session.scalar(
            select(Vacancy)
            .where(Vacancy.id == interview.vacancy_id)
            .options(selectinload(Vacancy.questions))
        )
        organization = await self.session.get(Organization, interview.organization_id)
        assert vacancy is not None and organization is not None
        if (
            interview.status
            in (InterviewStatus.invited, InterviewStatus.opened, InterviewStatus.consented)
            and aware(interview.expires_at) < utcnow()
        ):
            transition(interview, InterviewStatus.expired)
            await self.session.commit()
        return interview, vacancy, organization

    async def open(self, token: str) -> tuple[Interview, Vacancy, Organization]:
        interview, vacancy, organization = await self.by_token(token)
        if interview.status == InterviewStatus.invited:
            transition(interview, InterviewStatus.opened)
            await self.session.commit()
        return interview, vacancy, organization

    async def submit_consent(
        self, token: str, payload: ConsentSubmit, *, ip: str | None, user_agent: str | None
    ) -> tuple[Interview, Vacancy, Organization]:
        interview, vacancy, organization = await self.by_token(token)
        if interview.status not in (InterviewStatus.invited, InterviewStatus.opened):
            if interview.status == InterviewStatus.consented:
                return interview, vacancy, organization
            raise ConflictError("Согласие уже зафиксировано или интервью недоступно")
        if not payload.personal_data_accepted or not payload.privacy_policy_accepted:
            raise ValidationFailedError(
                "Без согласия на обработку персональных данных и ознакомления с политикой "
                "интервью пройти нельзя"
            )
        documents = {doc.slug: doc for doc in consent_documents()}
        for slug, version in payload.document_versions.items():
            current = documents.get(slug) or load_document(slug)
            if current.version != version:
                raise ConflictError(
                    "Текст документов обновился — обновите страницу и прочитайте заново"
                )
        decisions = {
            "personal-data-consent": True,
            "privacy-policy": True,
            "newsletter-consent": payload.newsletter_accepted,
        }
        for slug, accepted in decisions.items():
            document = documents[slug]
            self.session.add(
                ConsentRecord(
                    organization_id=interview.organization_id,
                    interview_id=interview.id,
                    candidate_id=interview.candidate_id,
                    slug=slug,
                    version=document.version,
                    document_hash=document.hash,
                    accepted=accepted,
                    ip=ip,
                    user_agent=(user_agent or "")[:512] or None,
                )
            )
        interview.consent_full_name = payload.full_name
        interview.consent_email = payload.email.lower()
        interview.newsletter_opt_in = payload.newsletter_accepted
        interview.consent_ip = ip
        interview.consent_user_agent = (user_agent or "")[:512] or None
        candidate = interview.candidate
        if payload.newsletter_accepted:
            candidate.newsletter_opt_in = True
        if not candidate.full_name.strip() or candidate.full_name == candidate.email.split("@")[0]:
            candidate.full_name = payload.full_name
        if interview.status == InterviewStatus.invited:
            transition(interview, InterviewStatus.opened)
        transition(interview, InterviewStatus.consented)
        await self.session.commit()
        return interview, vacancy, organization
