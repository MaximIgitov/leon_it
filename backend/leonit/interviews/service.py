"""Прохождение интервью: старт, показ вопросов, запись и загрузка ответов."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.accounts.models import Organization, User
from leonit.ai.gateway import get_tts
from leonit.ai.providers.base import ProviderError
from leonit.ai.tts_cache import get_or_synthesize
from leonit.candidates.models import Interview, InterviewStatus
from leonit.candidates.service import InterviewService, transition
from leonit.core.authz import Actor, authorize
from leonit.core.config import get_settings
from leonit.core.errors import ConflictError, NotFoundError, ValidationFailedError
from leonit.core.logging import get_logger
from leonit.core.storage import get_storage
from leonit.core.time import aware, utcnow
from leonit.interviews.models import Answer, AnswerStatus, InterviewEvent
from leonit.interviews.schemas import (
    EVENT_KINDS,
    AnswerComplete,
    ClientEvent,
    SnapshotQuestion,
)
from leonit.jobs import service as jobs
from leonit.media.service import sign_media_url
from leonit.notifications.service import queue_email
from leonit.notifications.templates import interview_completed_email
from leonit.vacancies.models import Vacancy
from leonit.vacancies.service import settings_of

log = get_logger(__name__)

UPLOAD_CHUNK_MAX_BYTES = 16 * 1024 * 1024
MAX_ANSWER_BYTES = 400 * 1024 * 1024
ANSWER_PROCESS_JOB = "answer.process"
INTERVIEW_PROCESS_JOB = "interview.process"

_EXTENSIONS = {
    "video/webm": "webm",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
}


def _extension(mime_type: str) -> str:
    base = mime_type.split(";", 1)[0].strip().lower()
    return _EXTENSIONS.get(base, "bin")


def build_question_snapshot(vacancy: Vacancy) -> list[dict[str, Any]]:
    """Вопросы с уже вычисленными лимитами: правки вакансии дальше не влияют."""
    snapshot = []
    for index, question in enumerate(sorted(vacancy.questions, key=lambda q: q.position)):
        snapshot.append(
            {
                "id": str(question.id),
                "index": index,
                "kind": question.kind.value,
                "text": question.text,
                "prep_seconds": (
                    question.prep_seconds
                    if question.prep_seconds is not None
                    else vacancy.prep_seconds
                ),
                "max_answer_seconds": (
                    question.max_answer_seconds
                    if question.max_answer_seconds is not None
                    else vacancy.max_answer_seconds
                ),
                "retakes_allowed": (
                    question.retakes_allowed
                    if question.retakes_allowed is not None
                    else vacancy.retakes_allowed
                ),
                "allows_followup": question.allows_followup,
                "competency_ids": question.competency_ids,
                # Подсказки оценщику: в снимке есть, кандидату не отдаются.
                "expected_points": question.expected_points,
            }
        )
    return snapshot


def public_question(item: dict[str, Any]) -> SnapshotQuestion:
    return SnapshotQuestion(
        id=item["id"],
        index=item["index"],
        kind=item["kind"],
        text=item["text"],
        prep_seconds=item["prep_seconds"],
        max_answer_seconds=item["max_answer_seconds"],
        retakes_allowed=item["retakes_allowed"],
        allows_followup=item["allows_followup"],
    )


class InterviewRoomService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.storage = get_storage()

    # ------------------------------------------------------------ helpers

    async def _load(self, token: str) -> tuple[Interview, Vacancy, Organization]:
        return await InterviewService(self.session).by_token(token)

    @staticmethod
    def _require_in_progress(interview: Interview) -> None:
        if interview.status != InterviewStatus.in_progress:
            raise ConflictError("Интервью не в процессе прохождения")

    @staticmethod
    def _question(interview: Interview, index: int) -> dict[str, Any]:
        snapshot = interview.question_snapshot or []
        if index < 0 or index >= len(snapshot):
            raise NotFoundError("Такого вопроса нет")
        if index > interview.current_question_index:
            raise ConflictError("Этот вопрос ещё не открыт")
        return snapshot[index]

    async def _answers(self, interview_id: UUID) -> list[Answer]:
        rows = await self.session.scalars(
            select(Answer)
            .where(Answer.interview_id == interview_id)
            .order_by(Answer.question_index, Answer.attempt)
        )
        return list(rows)

    async def _revealed_at(self, interview_id: UUID) -> dict[int, datetime]:
        rows = await self.session.execute(
            select(InterviewEvent.question_index, InterviewEvent.at_server)
            .where(
                InterviewEvent.interview_id == interview_id,
                InterviewEvent.kind == "question_revealed",
            )
            .order_by(InterviewEvent.at_server.asc())
        )
        revealed: dict[int, datetime] = {}
        for index, at_server in rows.all():
            if index is not None and index not in revealed:
                revealed[index] = aware(at_server)  # type: ignore[assignment]
        return revealed

    def _event(
        self,
        interview: Interview,
        kind: str,
        *,
        source: str = "server",
        question_index: int | None = None,
        answer_id: UUID | None = None,
        at_client_ms: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> InterviewEvent:
        event = InterviewEvent(
            interview_id=interview.id,
            kind=kind,
            source=source,
            question_index=question_index,
            answer_id=answer_id,
            at_client_ms=at_client_ms,
            # Время задаём сразу: значение нужно в ответе до flush в базу.
            at_server=utcnow(),
            payload=payload or {},
        )
        self.session.add(event)
        return event

    # -------------------------------------------------------------- flow

    async def start(self, token: str, client_info: dict[str, Any]) -> Interview:
        interview, vacancy, _ = await self._load(token)
        if interview.status == InterviewStatus.in_progress:
            return interview
        if interview.status != InterviewStatus.consented:
            raise ConflictError("Сначала нужно подтвердить согласия")
        if not vacancy.questions:
            raise ValidationFailedError("В вакансии нет вопросов")
        interview.question_snapshot = build_question_snapshot(vacancy)
        interview.settings_snapshot = settings_of(vacancy).model_dump()
        interview.client_info = {k: v for k, v in client_info.items() if isinstance(k, str)}
        interview.current_question_index = 0
        transition(interview, InterviewStatus.in_progress)
        self._event(interview, "interview_started", payload={"client_info": interview.client_info})
        await self.session.commit()
        return interview

    async def state(self, token: str) -> tuple[Interview, list[Answer], dict[int, datetime]]:
        interview, _, _ = await self._load(token)
        answers = await self._answers(interview.id)
        revealed = await self._revealed_at(interview.id)
        return interview, answers, revealed

    async def reveal(
        self, token: str, index: int
    ) -> tuple[dict[str, Any], datetime, str | None, str | None]:
        interview, _, _ = await self._load(token)
        self._require_in_progress(interview)
        question = self._question(interview, index)
        revealed = await self._revealed_at(interview.id)
        if index in revealed:
            # Повторный показ (перезагрузка страницы) — факт для integrity, время не сдвигаем.
            self._event(interview, "question_re_revealed", question_index=index)
            revealed_at = revealed[index]
        else:
            event = self._event(interview, "question_revealed", question_index=index)
            revealed_at = event.at_server
        audio_url = audio_type = None
        settings = interview.settings_snapshot or {}
        if settings.get("tts_enabled", True):
            try:
                key, content_type = await get_or_synthesize(
                    self.storage, get_tts(), question["text"], settings.get("voice")
                )
                audio_url = sign_media_url(key, ttl_s=1800, content_type=content_type)
                audio_type = content_type
            except ProviderError as error:
                # Без озвучки интервью продолжается: текст вопроса на экране всегда.
                log.warning("tts.unavailable interview=%s error=%s", interview.id, error)
        await self.session.commit()
        return question, revealed_at, audio_url, audio_type

    async def create_answer(self, token: str, index: int, mime_type: str) -> Answer:
        interview, _, _ = await self._load(token)
        self._require_in_progress(interview)
        question = self._question(interview, index)
        if index != interview.current_question_index:
            raise ConflictError("Отвечать можно только на текущий вопрос")
        answers = [a for a in await self._answers(interview.id) if a.question_index == index]
        # Незавершённая запись (обрыв связи) считается брошенной, новая — следующая попытка.
        for answer in answers:
            if answer.status == AnswerStatus.recording:
                answer.status = AnswerStatus.abandoned
                answer.is_final = False
        attempts_used = len(answers)
        if attempts_used > question["retakes_allowed"]:
            raise ConflictError("Лимит перезаписей исчерпан")
        attempt = attempts_used + 1
        answer = Answer(
            interview_id=interview.id,
            question_index=index,
            question_id=question["id"],
            attempt=attempt,
            status=AnswerStatus.recording,
            media_content_type=mime_type.split(";", 1)[0].strip().lower(),
        )
        self.session.add(answer)
        await self.session.flush()
        answer.media_key = (
            f"interviews/{interview.id}/q{index:02d}-a{attempt}-{answer.id}.{_extension(mime_type)}"
        )
        self._event(
            interview,
            "answer_started",
            question_index=index,
            answer_id=answer.id,
            payload={"attempt": attempt, "mime_type": answer.media_content_type},
        )
        await self.session.commit()
        return answer

    async def _answer(self, interview: Interview, answer_id: UUID) -> Answer:
        answer = await self.session.get(Answer, answer_id)
        if answer is None or answer.interview_id != interview.id:
            raise NotFoundError("Ответ не найден")
        return answer

    async def append_chunk(self, token: str, answer_id: UUID, offset: int, data: bytes) -> Answer:
        interview, _, _ = await self._load(token)
        self._require_in_progress(interview)
        answer = await self._answer(interview, answer_id)
        if answer.status != AnswerStatus.recording:
            raise ConflictError("Запись уже завершена")
        if not data:
            raise ValidationFailedError("Пустой кусок")
        if len(data) > UPLOAD_CHUNK_MAX_BYTES:
            raise ValidationFailedError("Слишком большой кусок")
        if offset + len(data) > MAX_ANSWER_BYTES:
            raise ValidationFailedError("Ответ слишком большой")
        assert answer.media_key
        # Хранилище само проверяет, что offset == текущему размеру; при
        # расхождении отдаст 409 с фактическим размером, и клиент продолжит с него.
        new_size = await self.storage.append(answer.media_key, data, offset)
        now = utcnow()
        answer.upload_offset = new_size
        answer.media_size = new_size
        answer.chunk_count += 1
        answer.first_chunk_at = answer.first_chunk_at or now
        answer.last_chunk_at = now
        await self.session.commit()
        return answer

    async def complete_answer(self, token: str, answer_id: UUID, payload: AnswerComplete) -> Answer:
        interview, _, _ = await self._load(token)
        self._require_in_progress(interview)
        answer = await self._answer(interview, answer_id)
        if answer.status == AnswerStatus.uploaded:
            return answer
        if answer.status != AnswerStatus.recording:
            raise ConflictError("Ответ уже обработан")
        assert answer.media_key
        actual = (
            await self.storage.size(answer.media_key)
            if await self.storage.exists(answer.media_key)
            else 0
        )
        if actual == 0:
            raise ValidationFailedError("Запись не загружена")
        if payload.size and payload.size != actual:
            raise ConflictError(f"Загружено {actual} байт из {payload.size}; докачайте остаток")
        now = utcnow()
        answer.status = AnswerStatus.uploaded
        answer.media_size = actual
        answer.upload_offset = actual
        answer.recording_ended_at = now
        answer.client_duration_ms = payload.client_duration_ms
        started = aware(answer.recording_started_at)
        answer.duration_ms = int((now - started).total_seconds() * 1000) if started else None
        if payload.mime_type:
            answer.media_content_type = payload.mime_type.split(";", 1)[0].strip().lower()
        # Зачётной становится последняя завершённая попытка.
        for other in await self._answers(interview.id):
            if other.question_index == answer.question_index and other.id != answer.id:
                other.is_final = False
        answer.is_final = True
        self._event(
            interview,
            "answer_completed",
            question_index=answer.question_index,
            answer_id=answer.id,
            payload={
                "size": actual,
                "duration_ms": answer.duration_ms,
                "chunks": answer.chunk_count,
            },
        )
        await jobs.enqueue(
            self.session,
            ANSWER_PROCESS_JOB,
            {"answer_id": str(answer.id), "interview_id": str(interview.id)},
            dedupe_key=f"answer:{answer.id}",
        )
        await self.session.commit()
        return answer

    async def next_question(self, token: str) -> Interview:
        interview, vacancy, organization = await self._load(token)
        self._require_in_progress(interview)
        index = interview.current_question_index
        answers = [
            a
            for a in await self._answers(interview.id)
            if a.question_index == index
            and a.status != AnswerStatus.recording
            and a.status != AnswerStatus.abandoned
        ]
        if not answers:
            raise ConflictError("Сначала запишите ответ на текущий вопрос")
        total = len(interview.question_snapshot or [])
        if index + 1 < total:
            interview.current_question_index = index + 1
            await self.session.commit()
            return interview
        await self._finish(interview, vacancy, organization)
        return interview

    async def _finish(
        self, interview: Interview, vacancy: Vacancy, organization: Organization
    ) -> None:
        transition(interview, InterviewStatus.completed)
        self._event(interview, "interview_completed")
        await jobs.enqueue(
            self.session,
            INTERVIEW_PROCESS_JOB,
            {"interview_id": str(interview.id)},
            dedupe_key=f"interview:{interview.id}",
        )
        recruiter = (
            await self.session.get(User, interview.invited_by_user_id)
            if interview.invited_by_user_id
            else None
        )
        if recruiter is not None and recruiter.is_active:
            subject, body = interview_completed_email(
                recipient_name=recruiter.full_name,
                candidate_name=interview.consent_full_name or interview.candidate.full_name,
                vacancy_title=vacancy.title,
                link=f"{get_settings().PUBLIC_URL}/vacancies/{vacancy.id}/interviews/{interview.id}",
            )
            await queue_email(
                self.session,
                organization_id=organization.id,
                to_email=recruiter.email,
                subject=subject,
                body_text=body,
                kind="interview.completed",
                interview_id=interview.id,
            )
        await self.session.commit()

    async def record_events(self, token: str, events: list[ClientEvent]) -> tuple[int, int]:
        interview, _, _ = await self._load(token)
        if interview.status not in (InterviewStatus.consented, InterviewStatus.in_progress):
            raise ConflictError("Интервью не активно")
        accepted = ignored = 0
        for item in events:
            if item.kind not in EVENT_KINDS:
                ignored += 1
                continue
            answer_id = None
            if item.answer_id:
                try:
                    answer_id = UUID(item.answer_id)
                except ValueError:
                    ignored += 1
                    continue
            self._event(
                interview,
                item.kind,
                source="client",
                question_index=item.question_index,
                answer_id=answer_id,
                at_client_ms=item.at_client_ms,
                payload=item.payload,
            )
            accepted += 1
        await self.session.commit()
        return accepted, ignored

    # ------------------------------------------------------------ staff side

    async def answers_for_staff(
        self, actor: Actor, interview_id: UUID
    ) -> tuple[Interview, list[Answer]]:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "interview.read", vacancy_id=interview.vacancy_id)
        return interview, await self._answers(interview.id)

    async def events_for_staff(self, actor: Actor, interview_id: UUID) -> list[InterviewEvent]:
        interview = await InterviewService(self.session).get(actor, interview_id)
        authorize(actor, "interview.read", vacancy_id=interview.vacancy_id)
        rows = await self.session.scalars(
            select(InterviewEvent)
            .where(InterviewEvent.interview_id == interview.id)
            .order_by(InterviewEvent.at_server.asc())
        )
        return list(rows)

    @staticmethod
    def media_url(answer: Answer, ttl_s: int = 900) -> str | None:
        if not answer.media_key or answer.status in (
            AnswerStatus.recording,
            AnswerStatus.abandoned,
        ):
            return None
        return sign_media_url(answer.media_key, ttl_s=ttl_s, content_type=answer.media_content_type)
