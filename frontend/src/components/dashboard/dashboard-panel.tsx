"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

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
import { MetricTiles, TILE_COUNT, TILE_GRID } from "./metric-tiles";
import { PeriodSwitch } from "./period-switch";

const DailyChart = dynamic(() => import("./daily-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-64 w-full" />,
});

const PERIOD_STORAGE_KEY = "leonit.dashboard.period";
const DEFAULT_PERIOD: DashboardPeriod = "30";

function readStoredPeriod(): DashboardPeriod {
  try {
    const stored = window.localStorage.getItem(PERIOD_STORAGE_KEY);
    if (stored === "7" || stored === "30" || stored === "90" || stored === "all") return stored;
  } catch {
    /* приватный режим */
  }
  return DEFAULT_PERIOD;
}

function LoadingState() {
  return (
    <div className="space-y-4" aria-busy>
      <div className={TILE_GRID}>
        {Array.from({ length: TILE_COUNT }, (_, index) => (
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
  // Пока период не восстановлен из localStorage, запросов не делаем: иначе
  // первый рендер грузил бы «30 дней», а следующий — сохранённый период, и два
  // ответа гонялись бы за один стейт. На сервере localStorage нет, поэтому
  // начальное значение — null, а не значение из хранилища (иначе разъедется
  // гидрация).
  const [period, setPeriod] = useState<DashboardPeriod | null>(null);
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [series, setSeries] = useState<DashboardTimeseries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const changePeriod = (next: DashboardPeriod) => {
    setPeriod(next);
    try {
      window.localStorage.setItem(PERIOD_STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  };

  useEffect(() => setPeriod(readStoredPeriod()), []);

  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    if (period === null) return;
    // Быстрое переключение периода: ответ прошлого запроса не должен перезаписать
    // данные текущего, поэтому применяем только последний по счёту.
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    try {
      const [nextOverview, nextSeries] = await Promise.all([
        vacancyId ? dashboardApi.vacancy(vacancyId, period) : dashboardApi.overview(period),
        dashboardApi.timeseries(period, vacancyId),
      ]);
      if (seq !== requestSeq.current) return;
      setOverview(nextOverview);
      setSeries(nextSeries);
    } catch (caught) {
      if (seq !== requestSeq.current) return;
      setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить метрики");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [vacancyId, period]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">{toolbar}</div>
        <PeriodSwitch value={period ?? DEFAULT_PERIOD} onChange={changePeriod} />
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
              <RecommendationCard breakdown={overview.recommendation_breakdown} />
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
