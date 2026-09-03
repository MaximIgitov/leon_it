"""Агрегаты дашборда: воронка, сроки, баллы и согласие решений с рекомендацией ИИ.

Все цифры выводятся из таймстемпов интервью (``Interview.*_at``): переходы
статусов уже фиксируют момент каждого шага, отдельной таблицы событий для
метрик не нужно. Заключения берутся из ``evaluations`` модуля оценки: одна
строка на интервью (``interview_id`` уникален), в метрики попадают только
готовые (``status = done``) — заключение в работе, после «Переобработать» или
упавшее баллов и рекомендации не имеет.

Период фильтрует интервью по ``invited_at`` — это когортная воронка: «из
приглашённых за период столько-то дошли до конца». Ряд по дням, наоборот,
считает события по их собственным датам: приглашения, завершения и заключения
одного дня относятся к этому дню.

В SQL — только переносимые агрегаты (count/case): SQLite не знает
``percentile_cont`` и ``date_trunc``, а интервью в организации немного, поэтому
медианы, разбивка по дням и доли по заключениям считаются в Python по выборке
значений.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leonit.candidates.models import Interview, InterviewStatus
from leonit.core.authz import Actor, authorize, visible_vacancy_ids
from leonit.core.errors import NotFoundError, ValidationFailedError
from leonit.core.time import aware, utcnow
from leonit.dashboard.schemas import (
    DashboardOverview,
    DashboardTimeseries,
    DecisionBreakdown,
    FunnelStep,
    PeriodOut,
    RecommendationBreakdown,
    TimeseriesPoint,
    VacancyRef,
)
from leonit.evaluation.models import Evaluation, EvaluationStatus
from leonit.interviews.models import Answer, AnswerStatus
from leonit.vacancies.models import Vacancy, VacancyStatus

DEFAULT_PERIOD_DAYS = 30
# Ряд по дням не растягиваем на годы: «всё время» у старой организации
# режем до этого окна, чтобы ответ оставался разумного размера.
MAX_TIMESERIES_DAYS = 400

FUNNEL_LABELS: tuple[tuple[str, str], ...] = (
    ("invited", "Приглашены"),
    ("opened", "Открыли ссылку"),
    ("consented", "Дали согласие"),
    ("started", "Начали интервью"),
    ("completed", "Завершили"),
    ("evaluated", "Оценены ИИ"),
    ("decided", "Есть решение"),
)

# Решение человека ↔ рекомендация модели, которые считаются совпадением.
# «Пауза» и «нужна проверка» — не позиция, поэтому такие пары не участвуют.
AGREEMENT: dict[str, str] = {"advance": "fit", "reject": "no_fit"}
DEFINITE_RECOMMENDATIONS = frozenset(AGREEMENT.values())


# ------------------------------------------------------------------- period


@dataclass(frozen=True)
class Period:
    start: datetime | None  # None — всё время
    end: datetime

    @property
    def all_time(self) -> bool:
        return self.start is None

    def out(self) -> PeriodOut:
        return PeriodOut(from_=self.start, to=self.end, all_time=self.all_time)


def to_utc(value: datetime) -> datetime:
    # SQLite хранит даты без зоны и сравнивает их как строки: параметры
    # приводим к UTC, чтобы сравнение строк совпадало со сравнением моментов.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def resolve_period(
    start: datetime | None, end: datetime | None, *, all_time: bool = False
) -> Period:
    """Границы периода из параметров запроса; без параметров — последние 30 дней."""
    end_at = to_utc(end) if end is not None else utcnow()
    if all_time:
        start_at = None
    elif start is not None:
        start_at = to_utc(start)
    else:
        start_at = end_at - timedelta(days=DEFAULT_PERIOD_DAYS)
    if start_at is not None and start_at > end_at:
        raise ValidationFailedError("Начало периода позже его конца")
    return Period(start=start_at, end=end_at)


# -------------------------------------------------------------------- scope


@dataclass(frozen=True)
class Scope:
    """Какие интервью и вакансии видны: организация плюс периметр менеджера."""

    organization_id: UUID
    vacancy_ids: list[UUID] | None  # None — все вакансии организации
    vacancy: Vacancy | None = None

    def interviews(self) -> list[ColumnElement[bool]]:
        conditions = [Interview.organization_id == self.organization_id]
        if self.vacancy_ids is not None:
            # Пустой список даёт корректное «ничего» на обоих диалектах.
            conditions.append(Interview.vacancy_id.in_(self.vacancy_ids))
        return conditions

    def vacancies(self) -> list[ColumnElement[bool]]:
        conditions = [Vacancy.organization_id == self.organization_id]
        if self.vacancy_ids is not None:
            conditions.append(Vacancy.id.in_(self.vacancy_ids))
        return conditions


def _as_uuids(values: list[str]) -> list[UUID]:
    result: list[UUID] = []
    for value in values:
        try:
            result.append(UUID(value))
        except ValueError:
            # Периметр хранится строками; мусор в нём просто ничего не открывает.
            continue
    return result


# -------------------------------------------------------------- evaluations


@dataclass(frozen=True, slots=True)
class EvaluationRow:
    """Готовое заключение по интервью когорты вместе с решением человека."""

    decision: str | None
    fit_score: float | None
    recommendation: str | None
    quotes_found: int | None
    quotes_total: int | None

    @property
    def quotes_checked(self) -> bool:
        """Есть что проверять: модель привела хотя бы одну цитату."""
        return bool(self.quotes_total)

    @property
    def quotes_verified(self) -> bool:
        """Все цитаты заключения найдены в транскрипте дословно."""
        return self.quotes_checked and (self.quotes_found or 0) >= (self.quotes_total or 0)


# ------------------------------------------------------------------ helpers


def _count_if(condition: ColumnElement[bool]) -> ColumnElement[int]:
    # COUNT игнорирует NULL, а CASE без ELSE даёт NULL — условный счётчик без
    # диалектных функций.
    return func.count(case((condition, 1)))


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _hours(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 3600


def _median_hours(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 2)


# ------------------------------------------------------------------ service


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def scope(self, actor: Actor, vacancy_id: UUID | None) -> Scope:
        if vacancy_id is not None:
            vacancy = await self.session.scalar(
                select(Vacancy).where(
                    Vacancy.id == vacancy_id, Vacancy.organization_id == actor.organization_id
                )
            )
            if vacancy is None:
                raise NotFoundError("Вакансия не найдена")
            authorize(actor, "dashboard.read", vacancy_id=vacancy.id)
            return Scope(actor.organization_id, [vacancy.id], vacancy)
        authorize(actor, "dashboard.read")
        visible = visible_vacancy_ids(actor)
        return Scope(actor.organization_id, None if visible is None else _as_uuids(visible))

    @staticmethod
    def _in_period(period: Period) -> list[ColumnElement[bool]]:
        conditions = [Interview.invited_at <= period.end]
        if period.start is not None:
            conditions.append(Interview.invited_at >= period.start)
        return conditions

    async def overview(
        self, actor: Actor, *, period: Period, vacancy_id: UUID | None = None
    ) -> DashboardOverview:
        scope = await self.scope(actor, vacancy_id)
        cohort = [*scope.interviews(), *self._in_period(period)]

        counts = (
            await self.session.execute(
                select(
                    func.count(Interview.id),
                    func.count(Interview.opened_at),
                    func.count(Interview.consented_at),
                    func.count(Interview.started_at),
                    func.count(Interview.completed_at),
                    func.count(Interview.evaluated_at),
                    # decided_at не ставится при «паузе» до заключения — решение
                    # надёжнее считать по самому полю decision.
                    func.count(Interview.decision),
                    _count_if(Interview.decision == "advance"),
                    _count_if(Interview.decision == "reject"),
                    _count_if(Interview.decision == "hold"),
                    _count_if(
                        and_(
                            Interview.completed_at.is_not(None),
                            Interview.decision.is_(None),
                            Interview.status != InterviewStatus.cancelled,
                        )
                    ),
                ).where(*cohort)
            )
        ).one()
        (
            invited,
            opened,
            consented,
            started,
            completed,
            evaluated,
            decided,
            advance,
            reject,
            hold,
            pending,
        ) = (int(value or 0) for value in counts)

        funnel: list[FunnelStep] = []
        previous: int | None = None
        for (key, label), count in zip(
            FUNNEL_LABELS,
            (invited, opened, consented, started, completed, evaluated, decided),
            strict=True,
        ):
            funnel.append(
                FunnelStep(
                    key=key,
                    label=label,
                    count=count,
                    rate_from_previous=None if previous is None else _ratio(count, previous),
                    rate_from_invited=None if key == "invited" else _ratio(count, invited),
                )
            )
            previous = count

        now = utcnow()
        recent = (
            await self.session.execute(
                select(
                    _count_if(Interview.invited_at >= now - timedelta(days=7)),
                    _count_if(Interview.invited_at >= now - timedelta(days=30)),
                ).where(*scope.interviews())
            )
        ).one()
        active_vacancies = await self.session.scalar(
            select(func.count(Vacancy.id)).where(
                *scope.vacancies(), Vacancy.status == VacancyStatus.published
            )
        )

        to_complete, to_result = await self._durations(cohort)
        avg_retakes = await self._avg_retakes(cohort)
        evaluations = await self._evaluations(cohort)

        fit_scores = [row.fit_score for row in evaluations if row.fit_score is not None]
        recommendations = Counter(
            row.recommendation
            for row in evaluations
            if row.recommendation in RecommendationBreakdown.model_fields
        )
        pairs = [
            row
            for row in evaluations
            if row.decision in AGREEMENT and row.recommendation in DEFINITE_RECOMMENDATIONS
        ]
        agreed = sum(1 for row in pairs if AGREEMENT[row.decision or ""] == row.recommendation)
        # Доверие к заключению: у скольких заключений все цитаты найдены в
        # транскрипте дословно. Заключения без цитат проверять нечем — они не
        # участвуют ни в числителе, ни в знаменателе.
        checked = [row for row in evaluations if row.quotes_checked]
        verified = sum(1 for row in checked if row.quotes_verified)

        return DashboardOverview(
            period=period.out(),
            vacancy=VacancyRef(
                id=str(scope.vacancy.id),
                title=scope.vacancy.title,
                status=scope.vacancy.status.value,
            )
            if scope.vacancy is not None
            else None,
            invited=invited,
            completed=completed,
            evaluated=evaluated,
            decided=decided,
            awaiting_decision=pending,
            active_vacancies=int(active_vacancies or 0),
            interviews_last_7d=int(recent[0] or 0),
            interviews_last_30d=int(recent[1] or 0),
            completion_rate=_ratio(completed, invited),
            median_time_to_complete_h=_median_hours(to_complete),
            median_time_to_result_h=_median_hours(to_result),
            avg_fit_score=round(statistics.fmean(fit_scores), 1) if fit_scores else None,
            avg_retakes=avg_retakes,
            ai_agreement=_ratio(agreed, len(pairs)),
            ai_agreement_pairs=len(pairs),
            quote_verification_rate=_ratio(verified, len(checked)),
            unverified_quotes_evaluations=len(checked) - verified,
            flags_rate=0.0,
            funnel=funnel,
            recommendation_breakdown=RecommendationBreakdown(**recommendations),
            decision_breakdown=DecisionBreakdown(
                advance=advance, reject=reject, hold=hold, pending=pending
            ),
        )

    async def _durations(
        self, cohort: list[ColumnElement[bool]]
    ) -> tuple[list[float], list[float]]:
        """Часы от приглашения до завершения и от завершения до заключения."""
        rows = await self.session.execute(
            select(Interview.invited_at, Interview.completed_at, Interview.evaluated_at).where(
                *cohort, Interview.completed_at.is_not(None)
            )
        )
        to_complete: list[float] = []
        to_result: list[float] = []
        for invited_at, completed_at, evaluated_at in rows:
            invited_at, completed_at, evaluated_at = (
                aware(invited_at),
                aware(completed_at),
                aware(evaluated_at),
            )
            assert invited_at is not None and completed_at is not None
            to_complete.append(_hours(completed_at, invited_at))
            if evaluated_at is not None:
                to_result.append(_hours(evaluated_at, completed_at))
        return to_complete, to_result

    async def _avg_retakes(self, cohort: list[ColumnElement[bool]]) -> float | None:
        # Зачётный ответ с attempt = N означает N − 1 перезаписей на этот вопрос.
        value = await self.session.scalar(
            select(func.avg(Answer.attempt - 1))
            .select_from(Answer)
            .join(Interview, Interview.id == Answer.interview_id)
            .where(
                *cohort,
                Answer.is_final.is_(True),
                Answer.status.notin_([AnswerStatus.recording, AnswerStatus.abandoned]),
            )
        )
        return None if value is None else round(float(value), 2)

    async def _evaluations(self, cohort: list[ColumnElement[bool]]) -> list[EvaluationRow]:
        """Готовые заключения по интервью когорты.

        ``interview_id`` в ``evaluations`` уникален, поэтому строк не больше,
        чем интервью, и объединять их не нужно: список без «последнее
        побеждает». Заключения в работе и упавшие (``pending`` / ``failed``)
        не имеют баллов и в метрики не попадают.
        """
        rows = await self.session.execute(
            select(
                Interview.decision,
                Evaluation.fit_score,
                Evaluation.recommendation,
                Evaluation.quotes_found,
                Evaluation.quotes_total,
            )
            .join(Evaluation, Evaluation.interview_id == Interview.id)
            .where(*cohort, Evaluation.status == EvaluationStatus.done)
        )
        return [
            EvaluationRow(
                decision=decision,
                fit_score=None if fit is None else float(fit),
                recommendation=recommendation,
                quotes_found=quotes_found,
                quotes_total=quotes_total,
            )
            for decision, fit, recommendation, quotes_found, quotes_total in rows
        ]

    async def timeseries(
        self,
        actor: Actor,
        *,
        period: Period,
        vacancy_id: UUID | None = None,
        tz_offset_minutes: int = 0,
    ) -> DashboardTimeseries:
        scope = await self.scope(actor, vacancy_id)
        conditions = [*scope.interviews(), Interview.invited_at <= period.end]
        if period.start is not None:
            conditions.append(
                or_(
                    Interview.invited_at >= period.start,
                    Interview.completed_at >= period.start,
                    Interview.evaluated_at >= period.start,
                )
            )
        rows = (
            await self.session.execute(
                select(Interview.invited_at, Interview.completed_at, Interview.evaluated_at).where(
                    *conditions
                )
            )
        ).all()

        # Дни считаем в зоне пользователя: приглашение в 01:00 по Москве не
        # должно попадать во «вчера» только потому, что сервер живёт в UTC.
        zone = timezone(timedelta(minutes=tz_offset_minutes))

        def day_of(value: datetime | None) -> date | None:
            stamped = aware(value)
            if stamped is None or stamped < (period.start or stamped) or stamped > period.end:
                return None
            return stamped.astimezone(zone).date()

        buckets: dict[date, dict[str, int]] = {}

        def bump(day: date | None, key: str) -> None:
            if day is None:
                return
            buckets.setdefault(day, {"invited": 0, "completed": 0, "evaluated": 0})[key] += 1

        for invited_at, completed_at, evaluated_at in rows:
            bump(day_of(invited_at), "invited")
            bump(day_of(completed_at), "completed")
            bump(day_of(evaluated_at), "evaluated")

        last_day = period.end.astimezone(zone).date()
        if period.start is not None:
            first_day = period.start.astimezone(zone).date()
        else:
            first_day = min(buckets) if buckets else last_day
        first_day = max(first_day, last_day - timedelta(days=MAX_TIMESERIES_DAYS))

        points: list[TimeseriesPoint] = []
        day = first_day
        while day <= last_day:
            values = buckets.get(day, {})
            points.append(
                TimeseriesPoint(
                    date=day,
                    invited=values.get("invited", 0),
                    completed=values.get("completed", 0),
                    evaluated=values.get("evaluated", 0),
                )
            )
            day += timedelta(days=1)
        return DashboardTimeseries(
            period=period.out(),
            vacancy_id=str(scope.vacancy.id) if scope.vacancy is not None else None,
            points=points,
        )
