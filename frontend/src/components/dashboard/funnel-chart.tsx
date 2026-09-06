"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { FunnelStep } from "@/lib/api/dashboard";

import { formatCount, formatPercent } from "./format";

/*
 * Воронка кандидата: горизонтальные бары от приглашения до решения. Ширина —
 * доля от приглашённых, подпись справа — конверсия с предыдущего шага, чтобы
 * было видно, где именно теряются кандидаты.
 */
export function FunnelChart({ steps }: { steps: FunnelStep[] }) {
  const total = steps[0]?.count ?? 0;
  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Воронка</CardTitle>
        <CardDescription>Путь кандидата</CardDescription>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            За выбранный период приглашений не было.
          </p>
        ) : (
          <ol className="space-y-3">
            {steps.map((step, index) => {
              const share = total ? step.count / total : 0;
              return (
                <li key={step.key}>
                  <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                    <span className="truncate">{step.label}</span>
                    <span className="shrink-0 tabular-nums">
                      <span className="font-semibold">{formatCount(step.count)}</span>
                      {index > 0 ? (
                        <span className="ml-2 text-xs text-muted-foreground">
                          {formatPercent(step.rate_from_previous)}
                        </span>
                      ) : null}
                    </span>
                  </div>
                  <div
                    className="h-3 w-full overflow-hidden rounded-full bg-secondary"
                    role="img"
                    aria-label={`${step.label}: ${step.count} из ${total}`}
                  >
                    <div
                      className="h-full rounded-full transition-[width] duration-300"
                      style={{ width: `${Math.max(share * 100, step.count ? 2 : 0)}%`, background: "var(--brand-green)" }}
                    />
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
