"use client";

import { Bot, CheckCircle2, Gauge, Hourglass, Quote, Send } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { DashboardOverview } from "@/lib/api/dashboard";

import { formatCount, formatHours, formatPercent, formatScore, plural } from "./format";

type Tile = {
  label: string;
  value: string;
  hint: string;
  icon: React.ElementType;
};

/** Сетка плиток: две на телефоне, три на планшете, все шесть в одну строку на десктопе. */
export const TILE_GRID = "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6";
export const TILE_COUNT = 6;

function quoteHint(data: DashboardOverview): string {
  if (data.quote_verification_rate === null) return "заключений с цитатами пока нет";
  const unverified = data.unverified_quotes_evaluations;
  if (unverified === 0) return "во всех заключениях цитаты найдены в транскрипте";
  return `${unverified} ${plural(unverified, ["заключение", "заключения", "заключений"])} с неподтверждёнными цитатами`;
}

export function tiles(data: DashboardOverview): Tile[] {
  return [
    {
      label: "Приглашений",
      value: formatCount(data.invited),
      hint: `за 7 дней: ${formatCount(data.interviews_last_7d)}`,
      icon: Send,
    },
    {
      label: "Завершили",
      value: formatCount(data.completed),
      hint:
        data.completion_rate === null
          ? "конверсия появится после приглашений"
          : `${formatPercent(data.completion_rate)} · медиана ${formatHours(data.median_time_to_complete_h)}`,
      icon: CheckCircle2,
    },
    {
      label: "Средний балл",
      value: formatScore(data.avg_fit_score),
      hint: data.evaluated
        ? `оценено ${data.evaluated} ${plural(data.evaluated, ["интервью", "интервью", "интервью"])} · до результата ${formatHours(data.median_time_to_result_h)}`
        : "заключений пока нет",
      icon: Gauge,
    },
    {
      label: "Ждут решения",
      value: formatCount(data.awaiting_decision),
      hint: `решений принято: ${formatCount(data.decided)}`,
      icon: Hourglass,
    },
    {
      label: "Согласие с ИИ",
      value: formatPercent(data.ai_agreement),
      hint: data.ai_agreement_pairs
        ? `по ${data.ai_agreement_pairs} ${plural(data.ai_agreement_pairs, ["решению", "решениям", "решениям"])} «дальше»/«отказ»`
        : "нужны решения по оценённым кандидатам",
      icon: Bot,
    },
    {
      // Доверие к заключению: у какой доли заключений все цитаты подтверждены транскриптом.
      label: "Цитаты подтверждены",
      value: formatPercent(data.quote_verification_rate),
      hint: quoteHint(data),
      icon: Quote,
    },
  ];
}

export function MetricTiles({ data }: { data: DashboardOverview }) {
  return (
    <div className={TILE_GRID}>
      {tiles(data).map((tile) => (
        <Card key={tile.label}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-muted-foreground">{tile.label}</p>
              <tile.icon className="h-4 w-4 shrink-0 text-primary" aria-hidden />
            </div>
            <p className="mt-2 text-3xl font-bold tabular-nums tracking-tight">{tile.value}</p>
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={tile.hint}>
              {tile.hint}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
