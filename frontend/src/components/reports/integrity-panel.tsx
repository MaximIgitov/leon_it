"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Info, ShieldAlert, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  INTEGRITY_LEVEL_LABELS,
  type IntegrityLevel,
  type IntegrityObservation,
  type IntegrityReport,
} from "@/lib/api/reports";
import { cn } from "@/lib/utils";

const LEVEL_STYLES: Record<IntegrityLevel, string> = {
  info: "text-muted-foreground",
  attention: "text-amber-700 dark:text-amber-400",
  risk: "text-destructive",
};

export function IntegrityBadge({ report }: { report: IntegrityReport | null }) {
  if (!report || !report.checked) return null;
  const Icon = report.level === "info" ? ShieldCheck : ShieldAlert;
  return (
    <Badge variant={report.level === "risk" ? "destructive" : "secondary"} className="gap-1">
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {INTEGRITY_LEVEL_LABELS[report.level]}
      {report.flags > 0 ? ` · ${report.flags}` : ""}
    </Badge>
  );
}

function LevelIcon({ level }: { level: IntegrityLevel }) {
  const Icon = level === "info" ? Info : level === "attention" ? AlertTriangle : ShieldAlert;
  return <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", LEVEL_STYLES[level])} aria-hidden />;
}

/*
 * Достоверность записи: факты и наблюдения, а не приговор. Ревьюер может
 * подтвердить наблюдение или пометить его ложным срабатыванием — тогда оно
 * перестаёт учитываться в итоговом уровне и в метрике на дашборде.
 */
export function IntegrityPanel({
  report,
  onReview,
  readOnly = false,
}: {
  report: IntegrityReport | null;
  onReview?: (
    observation: IntegrityObservation,
    verdict: "confirmed" | "false_positive",
  ) => Promise<void> | void;
  readOnly?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  if (!report) return null;

  const key = (item: IntegrityObservation) => `${item.code}:${item.question_index ?? -1}`;

  const handle = async (
    item: IntegrityObservation,
    verdict: "confirmed" | "false_positive",
  ) => {
    if (!onReview) return;
    setBusy(key(item));
    try {
      await onReview(item, verdict);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle className="text-base">Достоверность записи</CardTitle>
        <IntegrityBadge report={report} />
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {!report.checked ? (
          <p className="text-muted-foreground">
            По этому интервью ещё нет данных: кандидат не начинал запись.
          </p>
        ) : report.observations.length === 0 ? (
          <p className="flex items-start gap-2 text-muted-foreground">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            Ничего необычного: кандидат не уходил с вкладки во время ответов, запись сделана
            браузером, длительности сходятся.
          </p>
        ) : (
          <ul className="space-y-3">
            {report.observations.map((item) => (
              <li
                key={key(item)}
                className={cn(
                  "rounded-lg border p-3",
                  item.review?.verdict === "false_positive" && "opacity-60",
                )}
              >
                <div className="flex items-start gap-2">
                  <LevelIcon level={item.level} />
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="font-medium">{item.title}</p>
                    <p className="text-muted-foreground">{item.detail}</p>
                    {item.review ? (
                      <p className="text-xs text-muted-foreground">
                        {item.review.verdict === "confirmed"
                          ? "Подтверждено"
                          : "Ложное срабатывание"}
                        {" · "}
                        {item.review.reviewer}
                        {item.review.comment ? ` · ${item.review.comment}` : ""}
                      </p>
                    ) : null}
                    {!readOnly && onReview ? (
                      <div className="flex flex-wrap gap-2 pt-1">
                        <Button
                          size="sm"
                          variant={item.review?.verdict === "confirmed" ? "default" : "outline"}
                          disabled={busy === key(item)}
                          onClick={() => handle(item, "confirmed")}
                        >
                          Подтвердить
                        </Button>
                        <Button
                          size="sm"
                          variant={
                            item.review?.verdict === "false_positive" ? "default" : "outline"
                          }
                          disabled={busy === key(item)}
                          onClick={() => handle(item, "false_positive")}
                        >
                          Ложное срабатывание
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">
          Это наблюдения по записи и событиям в комнате, а не вывод о честности кандидата.
          Система не распознаёт личность и не анализирует мимику — решение принимает человек.
        </p>
      </CardContent>
    </Card>
  );
}
