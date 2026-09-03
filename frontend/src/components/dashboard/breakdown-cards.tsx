"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { DecisionBreakdown, RecommendationBreakdown } from "@/lib/api/dashboard";
import { cn } from "@/lib/utils";

import { formatCount, formatPercent } from "./format";

type Slice = { key: string; label: string; value: number; className: string };

/*
 * Разбивка одним составным баром и списком: доли видны сразу, точные числа —
 * рядом. Цвета семантические (успех / отказ / внимание), чтобы совпадать с
 * бейджами рекомендаций и решений в карточке кандидата.
 */
function Breakdown({
  title,
  description,
  slices,
  empty,
}: {
  title: string;
  description: string;
  slices: Slice[];
  empty: string;
}) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">{empty}</p>
        ) : (
          <>
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label={title}>
              {slices
                .filter((slice) => slice.value > 0)
                .map((slice) => (
                  <div
                    key={slice.key}
                    className={cn("h-full", slice.className)}
                    style={{ width: `${(slice.value / total) * 100}%` }}
                    title={`${slice.label}: ${slice.value}`}
                  />
                ))}
            </div>
            <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {slices.map((slice) => (
                <li key={slice.key} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", slice.className)} />
                    {slice.label}
                  </span>
                  <span className="tabular-nums">
                    <span className="font-semibold">{formatCount(slice.value)}</span>
                    <span className="ml-1.5 text-xs text-muted-foreground">
                      {formatPercent(slice.value / total)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function RecommendationCard({
  breakdown,
  available,
}: {
  breakdown: RecommendationBreakdown;
  available: boolean;
}) {
  return (
    <Breakdown
      title="Рекомендации ИИ"
      description="Выводятся из баллов по рубрике по порогам"
      empty={available ? "Заключений за период ещё нет." : "Модуль оценки не подключён."}
      slices={[
        { key: "fit", label: "Подходит", value: breakdown.fit, className: "bg-success" },
        { key: "needs_check", label: "Нужна проверка", value: breakdown.needs_check, className: "bg-warning" },
        { key: "no_fit", label: "Не подходит", value: breakdown.no_fit, className: "bg-destructive" },
      ]}
    />
  );
}

export function DecisionCard({ breakdown }: { breakdown: DecisionBreakdown }) {
  return (
    <Breakdown
      title="Решения"
      description="Что решили рекрутеры и нанимающие менеджеры"
      empty="Завершённых интервью за период ещё нет."
      slices={[
        { key: "advance", label: "Дальше", value: breakdown.advance, className: "bg-success" },
        { key: "hold", label: "На паузе", value: breakdown.hold, className: "bg-warning" },
        { key: "reject", label: "Отказ", value: breakdown.reject, className: "bg-destructive" },
        { key: "pending", label: "Ждут решения", value: breakdown.pending, className: "bg-muted-foreground/40" },
      ]}
    />
  );
}
