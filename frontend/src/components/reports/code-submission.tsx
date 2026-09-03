"use client";

import { Code2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { CodeRunResult, CodeSubmission as CodeSubmissionData } from "@/lib/api/room";
import { languageLabel } from "@/lib/code";
import { cn } from "@/lib/utils";

export const RUN_STATUS_LABELS: Record<CodeRunResult["status"], string> = {
  ok: "Выполнен",
  error: "Ошибка",
  timeout: "Превышено время",
};

/** Результат запуска: статус, время, stdout/stderr. Общий для комнаты и отчёта. */
export function RunResultView({ result, className }: { result: CodeRunResult; className?: string }) {
  const variant = result.status === "ok" ? "default" : result.status === "error" ? "destructive" : "secondary";
  return (
    <div className={cn("space-y-2 text-xs", className)} data-testid="run-result">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={variant}>{RUN_STATUS_LABELS[result.status]}</Badge>
        <span className="text-muted-foreground">
          {result.duration_ms} мс
          {result.exit_code !== null ? ` · код выхода ${result.exit_code}` : ""}
          {result.ran_at ? ` · ${new Date(result.ran_at).toLocaleTimeString("ru-RU")}` : ""}
        </span>
      </div>
      {result.stdout ? (
        <pre className="thin-scrollbar max-h-48 overflow-auto rounded-md border bg-muted/40 p-2 font-mono leading-5">{result.stdout}</pre>
      ) : null}
      {result.stderr ? (
        <pre className="thin-scrollbar max-h-48 overflow-auto rounded-md border border-destructive/40 bg-destructive/5 p-2 font-mono leading-5 text-destructive">
          {result.stderr}
        </pre>
      ) : null}
      {!result.stdout && !result.stderr ? <p className="text-muted-foreground">Вывода нет.</p> : null}
    </div>
  );
}

/** Блок кода в карточке кандидата: язык, время отправки, исходник и результат запуска. */
export function CodeSubmission({
  submission,
  className,
}: {
  submission: CodeSubmissionData;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Code2 className="h-4 w-4 text-primary" />
        <span className="font-medium text-foreground">{languageLabel(submission.language)}</span>
        <span aria-hidden>·</span>
        <span>
          {submission.submitted_at
            ? `отправлен ${new Date(submission.submitted_at).toLocaleString("ru-RU")}`
            : "черновик, не отправлен"}
        </span>
      </div>
      <pre className="thin-scrollbar max-h-96 overflow-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-5">
        <code>{submission.source}</code>
      </pre>
      {submission.run_result ? <RunResultView result={submission.run_result} /> : null}
    </div>
  );
}
