import { apiFetch } from "./client";

/** Переключатель периода: последние N дней или всё время. */
export type DashboardPeriod = "7" | "30" | "90" | "all";

export const PERIOD_LABELS: Record<DashboardPeriod, string> = {
  "7": "7 дней",
  "30": "30 дней",
  "90": "90 дней",
  all: "Всё время",
};

export type PeriodBounds = {
  from: string | null;
  to: string;
  all_time: boolean;
};

export type FunnelStepKey =
  | "invited"
  | "opened"
  | "consented"
  | "started"
  | "completed"
  | "evaluated"
  | "decided";

export type FunnelStep = {
  key: FunnelStepKey;
  label: string;
  count: number;
  rate_from_previous: number | null;
  rate_from_invited: number | null;
};

export type RecommendationBreakdown = { fit: number; no_fit: number; needs_check: number };
export type DecisionBreakdown = { advance: number; reject: number; hold: number; pending: number };

export type DashboardOverview = {
  period: PeriodBounds;
  vacancy: { id: string; title: string; status: string } | null;
  invited: number;
  completed: number;
  evaluated: number;
  decided: number;
  awaiting_decision: number;
  active_vacancies: number;
  interviews_last_7d: number;
  interviews_last_30d: number;
  completion_rate: number | null;
  median_time_to_complete_h: number | null;
  median_time_to_result_h: number | null;
  avg_fit_score: number | null;
  avg_retakes: number | null;
  ai_agreement: number | null;
  ai_agreement_pairs: number;
  flags_rate: number;
  evaluation_available: boolean;
  funnel: FunnelStep[];
  recommendation_breakdown: RecommendationBreakdown;
  decision_breakdown: DecisionBreakdown;
};

export type TimeseriesPoint = {
  date: string;
  invited: number;
  completed: number;
  evaluated: number;
};

export type DashboardTimeseries = {
  period: PeriodBounds;
  vacancy_id: string | null;
  points: TimeseriesPoint[];
};

/** Параметры периода для запроса: N дней → `from`, «всё время» → `all_time`. */
export function periodParams(period: DashboardPeriod): URLSearchParams {
  const params = new URLSearchParams();
  if (period === "all") {
    params.set("all_time", "true");
  } else {
    const from = new Date();
    from.setDate(from.getDate() - Number(period));
    params.set("from", from.toISOString());
  }
  return params;
}

export const dashboardApi = {
  overview: (period: DashboardPeriod) =>
    apiFetch<DashboardOverview>(`/dashboard/overview?${periodParams(period)}`),
  vacancy: (vacancyId: string, period: DashboardPeriod) =>
    apiFetch<DashboardOverview>(`/dashboard/vacancies/${vacancyId}?${periodParams(period)}`),
  timeseries: (period: DashboardPeriod, vacancyId?: string | null) => {
    const params = periodParams(period);
    if (vacancyId) params.set("vacancy_id", vacancyId);
    // Дни считаются в зоне пользователя, а не сервера.
    params.set("tz_offset_minutes", String(-new Date().getTimezoneOffset()));
    return apiFetch<DashboardTimeseries>(`/dashboard/timeseries?${params}`);
  },
};
