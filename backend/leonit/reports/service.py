from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.accounts.models import Organization
from leonit.accounts.security import generate_link_token, hash_link_token
from leonit.candidates.models import Interview, InterviewStatus
from leonit.candidates.service import InterviewService, transition
from leonit.core.authz import Actor, authorize
from leonit.core.config import get_settings
from leonit.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from leonit.core.logging import get_logger
from leonit.core.time import aware, utcnow
from leonit.evaluation.models import Evaluation
from leonit.interviews.code import code_submission_out, report_transcript
from leonit.interviews.models import Answer, AnswerStatus
from leonit.interviews.service import InterviewRoomService
from leonit.notifications.outreach import schedule_candidate_feedback
from leonit.reports.models import ReportShare, ReportView, ReviewNote
from leonit.reports.schemas import DecisionIn, NoteIn, ShareCreate
from leonit.vacancies.models import Vacancy

log = get_logger(__name__)

DECIDABLE = frozenset(
    {
        InterviewStatus.completed,
        InterviewStatus.processing,
        InterviewStatus.evaluated,
        InterviewStatus.reviewed,
        InterviewStatus.advanced,
        InterviewStatus.rejected,
    }
)


def share_url(token: str) -> str:
    return f"{get_settings().PUBLIC_URL}/r/{token}"


def share_status(share: ReportShare) -> str:
    if share.revoked_at is not None:
        return "revoked"
    if aware(share.expires_at) < utcnow():
        return "expired"
    return "active"


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -------------------------------------------------------------- decision

    async def decide(self, actor: Actor, interview_id: UUID, payload: DecisionIn) -> Interview:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.decide", vacancy_id=interview.vacancy_id)
        if interview.status not in DECIDABLE:
            raise ConflictError("Решение можно принять после завершения интервью")
        interview.decision = payload.decision
        interview.decision_note = payload.note.strip() or None
        interview.decided_by_user_id = actor.user.id
        target = {
            "advance": InterviewStatus.advanced,
            "reject": InterviewStatus.rejected,
            "hold": InterviewStatus.reviewed,
        }[payload.decision]
        if interview.status != target:
            if interview.status in (InterviewStatus.completed, InterviewStatus.processing):
                # Решение до заключения модели: фиксируем, статус обработки не трогаем.
                interview.decided_at = utcnow()
            elif (
                target == InterviewStatus.reviewed and interview.status != InterviewStatus.evaluated
            ):
                interview.decided_at = utcnow()
            else:
                transition(interview, target)
        await self.session.commit()
        # Обратная связь кандидату по настройке «после решения» ставится здесь:
        # раньше решения её слать нельзя, а сбой планирования не отменяет решение.
        try:
            await schedule_candidate_feedback(self.session, interview, decided=True)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            log.exception("decision.feedback interview=%s failed", interview.id)
        return await InterviewService(self.session).get(actor, interview.id)

    # ----------------------------------------------------------------- notes

    async def list_notes(self, actor: Actor, interview_id: UUID) -> list[ReviewNote]:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.read", vacancy_id=interview.vacancy_id)
        return await self._notes(interview.id)

    async def _notes(self, interview_id: UUID) -> list[ReviewNote]:
        rows = await self.session.scalars(
            select(ReviewNote)
            .where(ReviewNote.interview_id == interview_id)
            .order_by(ReviewNote.created_at.asc())
        )
        return list(rows)

    async def add_note(self, actor: Actor, interview_id: UUID, payload: NoteIn) -> ReviewNote:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.decide", vacancy_id=interview.vacancy_id)
        note = ReviewNote(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            author_user_id=actor.user.id,
            author_label=actor.user.full_name or actor.user.email,
            text=payload.text.strip(),
            answer_id=UUID(payload.answer_id) if payload.answer_id else None,
            at_s=payload.at_s,
        )
        self.session.add(note)
        await self.session.commit()
        return note

    async def delete_note(self, actor: Actor, interview_id: UUID, note_id: UUID) -> None:
        interview = await InterviewService(self.session).get(actor, interview_id)
        note = await self.session.get(ReviewNote, note_id)
        if note is None or note.interview_id != interview.id:
            raise NotFoundError("Заметка не найдена")
        if note.author_user_id != actor.user.id:
            authorize(actor, "org.members")
        await self.session.delete(note)
        await self.session.commit()

    # ---------------------------------------------------------------- shares

    async def create_share(
        self, actor: Actor, interview_id: UUID, payload: ShareCreate
    ) -> tuple[ReportShare, str]:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.share", vacancy_id=interview.vacancy_id)
        token = generate_link_token()
        share = ReportShare(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            token_hash=hash_link_token(token),
            label=payload.label.strip(),
            created_by_user_id=actor.user.id,
            expires_at=utcnow() + timedelta(days=payload.expires_in_days),
            include_integrity=payload.include_integrity,
            allow_download=payload.allow_download,
        )
        self.session.add(share)
        await self.session.commit()
        return share, token

    async def list_shares(self, actor: Actor, interview_id: UUID) -> list[ReportShare]:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.share", vacancy_id=interview.vacancy_id)
        rows = await self.session.scalars(
            select(ReportShare)
            .where(ReportShare.interview_id == interview.id)
            .order_by(ReportShare.created_at.desc())
        )
        return list(rows)

    async def revoke_share(self, actor: Actor, interview_id: UUID, share_id: UUID) -> ReportShare:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.share", vacancy_id=interview.vacancy_id)
        share = await self.session.get(ReportShare, share_id)
        if share is None or share.interview_id != interview.id:
            raise NotFoundError("Ссылка не найдена")
        if share.revoked_at is None:
            share.revoked_at = utcnow()
            await self.session.commit()
        return share

    async def extend_share(
        self, actor: Actor, interview_id: UUID, share_id: UUID, days: int
    ) -> ReportShare:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.share", vacancy_id=interview.vacancy_id)
        share = await self.session.get(ReportShare, share_id)
        if share is None or share.interview_id != interview.id:
            raise NotFoundError("Ссылка не найдена")
        share.expires_at = utcnow() + timedelta(days=days)
        share.revoked_at = None
        await self.session.commit()
        return share

    async def share_views(self, actor: Actor, interview_id: UUID) -> list[ReportView]:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.share", vacancy_id=interview.vacancy_id)
        rows = await self.session.scalars(
            select(ReportView)
            .where(ReportView.interview_id == interview.id)
            .order_by(ReportView.created_at.desc())
            .limit(200)
        )
        return list(rows)

    # ---------------------------------------------------------------- public

    async def _share_by_token(self, token: str) -> tuple[ReportShare, Interview]:
        share = await self.session.scalar(
            select(ReportShare).where(ReportShare.token_hash == hash_link_token(token))
        )
        if share is None:
            raise NotFoundError("Ссылка на отчёт недействительна")
        if share_status(share) != "active":
            raise PermissionDeniedError("Срок ссылки истёк или она отозвана")
        interview = await self.session.scalar(
            select(Interview)
            .where(Interview.id == share.interview_id)
            .options(selectinload(Interview.candidate))
        )
        if interview is None:
            raise NotFoundError("Отчёт не найден")
        return share, interview

    # ------------------------------------------------------------ report body

    async def _final_answers(self, interview_id: UUID) -> list[Answer]:
        rows = await self.session.scalars(
            select(Answer)
            .where(Answer.interview_id == interview_id, Answer.is_final.is_(True))
            .order_by(Answer.question_index)
        )
        return list(rows)

    def _answer_rows(
        self, interview: Interview, answers: list[Answer], *, with_media: bool
    ) -> list[dict[str, Any]]:
        """Ответы с транскриптами; медиа-ссылки — только когда получатель вправе их видеть."""
        snapshot = {item["index"]: item for item in interview.question_snapshot or []}
        room = InterviewRoomService(self.session)
        return [
            {
                "id": str(a.id),
                "question_index": a.question_index,
                "question_text": (snapshot.get(a.question_index) or {}).get("text"),
                "attempt": a.attempt,
                "duration_ms": a.duration_ms,
                "media_url": (
                    room.media_url(a, ttl_s=900)
                    if with_media
                    and a.status not in (AnswerStatus.recording, AnswerStatus.abandoned)
                    else None
                ),
                "media_content_type": a.media_content_type,
                # Для вопроса с кодом транскрипт дополняется блоком кода.
                "transcript_text": report_transcript(a),
                "transcript_segments": a.transcript_segments,
                "status": a.status.value,
                "code_submission": code_submission_out(a.code_submission),
            }
            for a in answers
        ]

    async def report(
        self, actor: Actor, interview_id: UUID, *, with_media: bool = True
    ) -> dict[str, Any]:
        """Отчёт для сотрудника или интеграции: интервью, заключение, ответы."""
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "report.read", vacancy_id=interview.vacancy_id)
        vacancy = await self.session.get(Vacancy, interview.vacancy_id)
        answers = await self._final_answers(interview.id)
        return {
            "interview": interview,
            "vacancy_title": vacancy.title if vacancy else "",
            "evaluation": await self.evaluation_payload(interview.id),
            "answers": self._answer_rows(interview, answers, with_media=with_media),
        }

    async def public_report(
        self, token: str, *, ip: str | None, user_agent: str | None
    ) -> dict[str, Any]:
        share, interview = await self._share_by_token(token)
        vacancy = await self.session.get(Vacancy, interview.vacancy_id)
        organization = await self.session.get(Organization, interview.organization_id)
        assert vacancy is not None and organization is not None
        answers = await self._final_answers(interview.id)
        evaluation = await self.evaluation_payload(interview.id)
        share.view_count += 1
        share.last_viewed_at = utcnow()
        self.session.add(
            ReportView(
                share_id=share.id,
                interview_id=interview.id,
                what="report",
                ip=ip,
                user_agent=(user_agent or "")[:512] or None,
            )
        )
        await self.session.commit()
        return {
            "organization_name": organization.name,
            "vacancy_title": vacancy.title,
            "candidate_name": interview.consent_full_name or interview.candidate.full_name,
            "candidate_email": interview.candidate.email,
            "status": interview.status.value,
            "completed_at": aware(interview.completed_at),
            "decision": interview.decision,
            "decision_note": interview.decision_note,
            "evaluation": evaluation,
            "answers": self._answer_rows(interview, answers, with_media=True),
            "notes": await self._notes(interview.id),
            "can_decide": True,
            "can_note": True,
            "integrity": None,
            "expires_at": aware(share.expires_at),
        }

    async def evaluation_payload(self, interview_id: UUID) -> dict[str, Any] | None:
        return (await self.evaluation_payloads([interview_id])).get(interview_id)

    async def evaluation_payloads(
        self, interview_ids: list[UUID]
    ) -> dict[UUID, dict[str, Any] | None]:
        """Заключения модели по интервью одним запросом (для отчётов и списков).

        Строка возвращается в любом статусе (``pending`` после «Переобработать»,
        ``failed`` с текстом ошибки): получатель отчёта должен видеть, что оценка
        идёт или не удалась. Ранжирование по вакансии — ``evaluation.service.ranking``.
        """
        if not interview_ids:
            return {}
        rows = await self.session.scalars(
            select(Evaluation).where(Evaluation.interview_id.in_(interview_ids))
        )
        result: dict[UUID, dict[str, Any] | None] = dict.fromkeys(interview_ids)
        for evaluation in rows:
            result[evaluation.interview_id] = {
                "status": evaluation.status,
                "fit_score": evaluation.fit_score,
                "recommendation": evaluation.recommendation,
                "output": evaluation.output,
                "evaluated_at": aware(evaluation.evaluated_at).isoformat()
                if evaluation.evaluated_at
                else None,
            }
        return result

    async def public_decide(self, token: str, payload: DecisionIn, *, ip: str | None) -> Interview:
        share, interview = await self._share_by_token(token)
        if interview.status not in DECIDABLE:
            raise ConflictError("Решение можно принять после завершения интервью")
        interview.decision = payload.decision
        interview.decision_note = payload.note.strip() or None
        interview.decided_by_user_id = share.created_by_user_id
        target = {
            "advance": InterviewStatus.advanced,
            "reject": InterviewStatus.rejected,
            "hold": InterviewStatus.reviewed,
        }[payload.decision]
        if interview.status in (InterviewStatus.evaluated, InterviewStatus.reviewed) or (
            interview.status in (InterviewStatus.advanced, InterviewStatus.rejected)
            and target != InterviewStatus.reviewed
        ):
            if interview.status != target:
                transition(interview, target)
        else:
            interview.decided_at = utcnow()
        self.session.add(
            ReportView(
                share_id=share.id,
                interview_id=interview.id,
                what="decision",
                ip=ip,
                details={"decision": payload.decision, "label": share.label},
            )
        )
        await self.session.commit()
        return interview

    async def public_note(self, token: str, payload: NoteIn) -> ReviewNote:
        share, interview = await self._share_by_token(token)
        note = ReviewNote(
            organization_id=interview.organization_id,
            interview_id=interview.id,
            author_user_id=None,
            author_label=share.label or "По ссылке отчёта",
            text=payload.text.strip(),
            answer_id=UUID(payload.answer_id) if payload.answer_id else None,
            at_s=payload.at_s,
        )
        self.session.add(note)
        await self.session.commit()
        return note
