"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import {
  dashboardApi,
  type DashboardOverview,
  type DashboardPeriod,
  type DashboardTimeseries,
} from "@/lib/api/dashboard";

import { DecisionCard, RecommendationCard } from "./breakdown-cards";
import { FunnelChart } from "./funnel-chart";
import { MetricTiles } from "./metric-tiles";
import { PeriodSwitch } from "./period-switch";

const DailyChart = dynamic(() => import("./daily-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-64 w-full" />,
});

const PERIOD_STORAGE_KEY = "leonit.dashboard.period";

function readStoredPeriod(): DashboardPeriod {
  try {
    const stored = window.localStorage.getItem(PERIOD_STORAGE_KEY);
    if (stored === "7" || stored === "30" || stored === "90" || stored === "all") return stored;
  } catch {
    /* приватный режим */
  }
  return "30";
}

function LoadingState() {
  return (
    <div className="space-y-4" aria-busy>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-28" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-80" />
        <Skeleton className="h-80 lg:col-span-2" />
      </div>
    </div>
  );
}

/*
 * Один набор виджетов для организации и для вакансии: страница дашборда
 * передаёт выбранную вакансию (или ничего), вкладка «Метрики» вакансии — её id.
 */
export function DashboardPanel({
  vacancyId,
  toolbar,
}: {
  vacancyId?: string | null;
  toolbar?: React.ReactNode;
}) {
  const [period, setPeriod] = useState<DashboardPeriod>("30");
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [series, setSeries] = useState<DashboardTimeseries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => setPeriod(readStoredPeriod()), []);

  const changePeriod = (next: DashboardPeriod) => {
    setPeriod(next);
    try {
      window.localStorage.setItem(PERIOD_STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextOverview, nextSeries] = await Promise.all([
        vacancyId ? dashboardApi.vacancy(vacancyId, period) : dashboardApi.overview(period),
        dashboardApi.timeseries(period, vacancyId),
      ]);
      setOverview(nextOverview);
      setSeries(nextSeries);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить метрики");
    } finally {
      setLoading(false);
    }
  }, [vacancyId, period]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">{toolbar}</div>
        <PeriodSwitch value={period} onChange={changePeriod} />
      </div>

      {error ? (
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">{error}</p>
      ) : null}

      {loading && !overview ? (
        <LoadingState />
      ) : overview && series ? (
        <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"} aria-busy={loading}>
          <div className="space-y-4">
            <MetricTiles data={overview} />
            <div className="grid gap-4 lg:grid-cols-3">
              <FunnelChart steps={overview.funnel} />
              <Card className="lg:col-span-2">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">По дням</CardTitle>
                  <CardDescription>Приглашения, завершённые интервью и заключения ИИ</CardDescription>
                </CardHeader>
                <CardContent>
                  <DailyChart points={series.points} />
                </CardContent>
              </Card>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <RecommendationCard
                breakdown={overview.recommendation_breakdown}
                available={overview.evaluation_available}
              />
              <DecisionCard breakdown={overview.decision_breakdown} />
            </div>
            <p className="text-xs text-muted-foreground">
              Воронка считается по приглашённым за период; «пульс» за 7 дней и активные вакансии — без
              учёта периода. Доля integrity-флагов появится вместе с модулем достоверности
              {overview.avg_retakes !== null ? ` · перезаписей на ответ в среднем: ${overview.avg_retakes.toFixed(2)}` : ""}.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
