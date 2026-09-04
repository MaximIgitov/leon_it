from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PeriodOut(BaseModel):
    """Фактические границы периода, по которым считались цифры.

    ``from`` пустой означает «всё время»: клиент показывает подпись, а не дату.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: datetime | None = Field(alias="from")
    to: datetime
    all_time: bool


class VacancyRef(BaseModel):
    id: str
    title: str
    status: str


class FunnelStep(BaseModel):
    key: str
    label: str
    count: int
    # Конверсии считаются от предыдущего шага и от числа приглашённых;
    # None — делить не на что (нулевой предыдущий шаг или сам первый шаг).
    rate_from_previous: float | None
    rate_from_invited: float | None


class RecommendationBreakdown(BaseModel):
    fit: int = 0
    no_fit: int = 0
    needs_check: int = 0


class DecisionBreakdown(BaseModel):
    advance: int = 0
    reject: int = 0
    hold: int = 0
    # Завершили интервью, решения ещё нет.
    pending: int = 0


class DashboardOverview(BaseModel):
    period: PeriodOut
    vacancy: VacancyRef | None

    invited: int
    completed: int
    evaluated: int
    decided: int
    awaiting_decision: int
    active_vacancies: int
    # Не зависят от выбранного периода — «пульс» организации или вакансии.
    interviews_last_7d: int
    interviews_last_30d: int

    completion_rate: float | None
    median_time_to_complete_h: float | None
    median_time_to_result_h: float | None
    avg_fit_score: float | None
    avg_retakes: float | None
    # Доля решений «дальше»/«отказ», совпавших с рекомендацией модели;
    # ai_agreement_pairs — сколько пар решение ↔ рекомендация участвовало.
    ai_agreement: float | None
    ai_agreement_pairs: int
    quote_verification_rate: float | None = Field(
        description=(
            "Доверие к заключению: доля готовых заключений, у которых все цитаты "
            "найдены в транскрипте дословно (quotes_found = quotes_total). "
            "Заключения без цитат не участвуют; null — проверять пока нечего."
        )
    )
    unverified_quotes_evaluations: int = Field(
        description="Число заключений с неподтверждёнными цитатами (quotes_found < quotes_total)."
    )
    flags_rate: float = Field(
        description=(
            "Доля завершённых интервью, где есть непогашенные наблюдения о "
            "достоверности записи (ложные срабатывания, отмеченные ревьюером, "
            "не считаются)."
        )
    )

    funnel: list[FunnelStep]
    recommendation_breakdown: RecommendationBreakdown
    decision_breakdown: DecisionBreakdown


class TimeseriesPoint(BaseModel):
    date: date
    invited: int
    completed: int
    evaluated: int


class DashboardTimeseries(BaseModel):
    period: PeriodOut
    vacancy_id: str | None
    points: list[TimeseriesPoint]
