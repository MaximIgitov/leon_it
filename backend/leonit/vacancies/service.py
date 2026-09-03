from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leonit.core.authz import Actor, authorize, visible_vacancy_ids
from leonit.core.errors import NotFoundError, ValidationFailedError
from leonit.core.time import aware, utcnow
from leonit.vacancies.models import (
    CandidateFeedbackMode,
    Question,
    QuestionKind,
    Vacancy,
    VacancyStatus,
)
from leonit.vacancies.schemas import (
    InterviewSettings,
    QuestionIn,
    QuestionOut,
    RubricCompetency,
    VacancyCreate,
    VacancyDetailOut,
    VacancyListItem,
    VacancyOut,
    VacancyUpdate,
)

SETTINGS_FIELDS = tuple(InterviewSettings.model_fields)


class VacancyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, actor: Actor, status: VacancyStatus | None = None) -> list[Vacancy]:
        authorize(actor, "vacancy.read")
        stmt = (
            select(Vacancy)
            .where(Vacancy.organization_id == actor.organization_id)
            .options(selectinload(Vacancy.questions))
            .order_by(Vacancy.updated_at.desc())
        )
        if status is not None:
            stmt = stmt.where(Vacancy.status == status)
        visible = visible_vacancy_ids(actor)
        if visible is not None:
            # Нанимающий менеджер видит только допущенные вакансии; пустой
            # список — ни одной.
            if not visible:
                return []
            stmt = stmt.where(Vacancy.id.in_([UUID(item) for item in visible]))
        return list((await self.session.scalars(stmt)).all())

    async def get(self, actor: Actor, vacancy_id: UUID, *, action: str = "vacancy.read") -> Vacancy:
        # populate_existing: объект мог остаться в identity map с устаревшей
        # коллекцией вопросов после replace_questions — перечитываем из базы.
        vacancy = await self.session.scalar(
            select(Vacancy)
            .where(Vacancy.id == vacancy_id, Vacancy.organization_id == actor.organization_id)
            .options(selectinload(Vacancy.questions))
            .execution_options(populate_existing=True)
        )
        if vacancy is None:
            raise NotFoundError("Вакансия не найдена")
        authorize(actor, action, vacancy_id=vacancy.id)
        return vacancy

    async def create(self, actor: Actor, payload: VacancyCreate) -> Vacancy:
        authorize(actor, "vacancy.write")
        vacancy = Vacancy(
            organization_id=actor.organization_id,
            created_by_user_id=actor.user.id,
            title=payload.title,
            description=payload.description,
            requirements=payload.requirements,
            skills=payload.skills,
            level=payload.level,
        )
        self.session.add(vacancy)
        await self.session.commit()
        return await self.get(actor, vacancy.id, action="vacancy.write")

    async def update(self, actor: Actor, vacancy_id: UUID, payload: VacancyUpdate) -> Vacancy:
        vacancy = await self.get(actor, vacancy_id, action="vacancy.write")
        if vacancy.status == VacancyStatus.archived:
            raise ValidationFailedError("Архивную вакансию нельзя редактировать")
        for field in ("title", "description", "requirements", "skills", "level"):
            if field in payload.model_fields_set:
                setattr(vacancy, field, getattr(payload, field))
        if payload.rubric is not None:
            vacancy.rubric = [item.model_dump() for item in payload.rubric]
            known = {item.id for item in payload.rubric}
            for question in vacancy.questions:
                question.competency_ids = [c for c in question.competency_ids if c in known]
        if payload.settings is not None:
            data = payload.settings.model_dump()
            data["candidate_feedback_mode"] = CandidateFeedbackMode(data["candidate_feedback_mode"])
            for field, value in data.items():
                setattr(vacancy, field, value)
        await self.session.commit()
        return await self.get(actor, vacancy.id, action="vacancy.write")

    async def replace_questions(
        self, actor: Actor, vacancy_id: UUID, items: list[QuestionIn]
    ) -> Vacancy:
        vacancy = await self.get(actor, vacancy_id, action="vacancy.write")
        if vacancy.status == VacancyStatus.archived:
            raise ValidationFailedError("Архивную вакансию нельзя редактировать")
        known_competencies = {item["id"] for item in vacancy.rubric}
        existing = {str(question.id): question for question in vacancy.questions}
        kept: list[Question] = []
        for position, item in enumerate(items):
            unknown = set(item.competency_ids) - known_competencies
            if unknown:
                raise ValidationFailedError(
                    f"Вопрос {position + 1} ссылается на неизвестные компетенции: "
                    f"{', '.join(sorted(unknown))}"
                )
            question = existing.pop(item.id, None) if item.id else None
            if question is None:
                question = Question(vacancy_id=vacancy.id, position=position)
                self.session.add(question)
            # Позиции переставляются в два прохода из-за уникального индекса.
            question.position = -(position + 1)
            question.kind = QuestionKind(item.kind)
            question.text = item.text.strip()
            question.expected_points = item.expected_points
            question.competency_ids = item.competency_ids
            question.allows_followup = item.allows_followup
            question.prep_seconds = item.prep_seconds
            question.max_answer_seconds = item.max_answer_seconds
            question.retakes_allowed = item.retakes_allowed
            kept.append(question)
        for question in existing.values():
            await self.session.delete(question)
        await self.session.flush()
        for position, question in enumerate(kept):
            question.position = position
        await self.session.commit()
        return await self.get(actor, vacancy.id, action="vacancy.write")

    async def publish(self, actor: Actor, vacancy_id: UUID) -> Vacancy:
        vacancy = await self.get(actor, vacancy_id, action="vacancy.write")
        problems = []
        if not vacancy.title.strip():
            problems.append("нет названия")
        if not vacancy.description.strip() and not vacancy.requirements.strip():
            problems.append("нет описания или требований")
        if not vacancy.questions:
            problems.append("нет ни одного вопроса")
        if problems:
            raise ValidationFailedError("Нельзя опубликовать: " + ", ".join(problems))
        vacancy.status = VacancyStatus.published
        vacancy.published_at = utcnow()
        vacancy.archived_at = None
        await self.session.commit()
        return await self.get(actor, vacancy.id, action="vacancy.write")

    async def unpublish(self, actor: Actor, vacancy_id: UUID) -> Vacancy:
        vacancy = await self.get(actor, vacancy_id, action="vacancy.write")
        vacancy.status = VacancyStatus.draft
        await self.session.commit()
        return await self.get(actor, vacancy.id, action="vacancy.write")

    async def archive(self, actor: Actor, vacancy_id: UUID) -> Vacancy:
        vacancy = await self.get(actor, vacancy_id, action="vacancy.write")
        vacancy.status = VacancyStatus.archived
        vacancy.archived_at = utcnow()
        await self.session.commit()
        return await self.get(actor, vacancy.id, action="vacancy.write")

    async def restore(self, actor: Actor, vacancy_id: UUID) -> Vacancy:
        vacancy = await self.get(actor, vacancy_id, action="vacancy.write")
        if vacancy.status == VacancyStatus.archived:
            vacancy.status = VacancyStatus.draft
            vacancy.archived_at = None
            await self.session.commit()
        return await self.get(actor, vacancy.id, action="vacancy.write")

    async def count_questions(self, vacancy_ids: list[UUID]) -> dict[UUID, int]:
        if not vacancy_ids:
            return {}
        rows = await self.session.execute(
            select(Question.vacancy_id, func.count())
            .where(Question.vacancy_id.in_(vacancy_ids))
            .group_by(Question.vacancy_id)
        )
        return {vacancy_id: count for vacancy_id, count in rows.all()}


def settings_of(vacancy: Vacancy) -> InterviewSettings:
    data = {field: getattr(vacancy, field) for field in SETTINGS_FIELDS}
    data["candidate_feedback_mode"] = vacancy.candidate_feedback_mode.value
    return InterviewSettings(**data)


def question_out(question: Question) -> QuestionOut:
    return QuestionOut(
        id=str(question.id),
        position=question.position,
        kind=question.kind.value,  # type: ignore[arg-type]
        text=question.text,
        expected_points=question.expected_points,
        competency_ids=question.competency_ids,
        allows_followup=question.allows_followup,
        prep_seconds=question.prep_seconds,
        max_answer_seconds=question.max_answer_seconds,
        retakes_allowed=question.retakes_allowed,
    )


def vacancy_out(vacancy: Vacancy) -> VacancyOut:
    return VacancyOut(
        id=str(vacancy.id),
        title=vacancy.title,
        description=vacancy.description,
        requirements=vacancy.requirements,
        skills=vacancy.skills,
        level=vacancy.level,  # type: ignore[arg-type]
        language=vacancy.language,
        status=vacancy.status.value,  # type: ignore[arg-type]
        rubric=[RubricCompetency(**item) for item in vacancy.rubric],
        settings=settings_of(vacancy),
        question_count=len(vacancy.questions),
        created_at=aware(vacancy.created_at),  # type: ignore[arg-type]
        updated_at=aware(vacancy.updated_at),  # type: ignore[arg-type]
        published_at=aware(vacancy.published_at),
        archived_at=aware(vacancy.archived_at),
    )


def vacancy_detail_out(vacancy: Vacancy) -> VacancyDetailOut:
    base = vacancy_out(vacancy)
    return VacancyDetailOut(
        **base.model_dump(),
        questions=[question_out(question) for question in vacancy.questions],
    )


def vacancy_list_item(vacancy: Vacancy) -> VacancyListItem:
    return VacancyListItem(
        id=str(vacancy.id),
        title=vacancy.title,
        status=vacancy.status.value,  # type: ignore[arg-type]
        level=vacancy.level,  # type: ignore[arg-type]
        skills=vacancy.skills,
        question_count=len(vacancy.questions),
        created_at=aware(vacancy.created_at),  # type: ignore[arg-type]
        updated_at=aware(vacancy.updated_at),  # type: ignore[arg-type]
        published_at=aware(vacancy.published_at),
    )
