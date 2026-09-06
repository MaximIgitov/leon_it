"use client";

import { RowsSkeleton } from "@/components/ui/skeleton";

import Link from "@/lib/router";
import { useCallback, useEffect, useState } from "react";
import { Trophy } from "lucide-react";

import { InterviewStatusBadge } from "@/components/candidates/status-badge";
import { RecommendationBadge } from "@/components/reports/evaluation-view";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import type { InterviewStatus } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";
import { DECISION_LABELS, reportsApi, type Decision, type RankingRow } from "@/lib/api/reports";

/*
 * Ранжирование по вакансии: два независимых измерения — соответствие
 * (сортировка, «нужна проверка» закреплена сверху) и решение человека.
 * Достоверность (integrity) появится отдельной колонкой в PR 13 плана.
 */
export function RankingTable({ vacancyId }: { vacancyId: string }) {
  const { toast } = useToast();
  const [rows, setRows] = useState<RankingRow[] | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await reportsApi.ranking(vacancyId));
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setRows([]);
        return;
      }
      toast({ variant: "destructive", title: error instanceof ApiError ? error.message : "Не удалось загрузить рейтинг" });
    }
  }, [vacancyId, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  if (rows === null) return <RowsSkeleton />;
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <Trophy className="mx-auto h-8 w-8 text-muted-foreground" />
        <p className="mt-3 font-medium">Пока некого ранжировать</p>
        <p className="mt-1 text-sm text-muted-foreground">Список появится, когда кандидаты пройдут интервью.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">#</TableHead>
            <TableHead>Кандидат</TableHead>
            <TableHead>Соответствие</TableHead>
            <TableHead>Статус</TableHead>
            <TableHead>Решение</TableHead>
            <TableHead>Оценено</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={row.interview_id}>
              <TableCell className="text-muted-foreground">{index + 1}</TableCell>
              <TableCell>
                <Link href={`/vacancies/${vacancyId}/interviews/${row.interview_id}`} className="table-row-link font-medium hover:underline">
                  {row.candidate_name}
                </Link>
                <div className="text-xs text-muted-foreground">{row.candidate_email}</div>
              </TableCell>
              <TableCell>
                <RecommendationBadge value={row.recommendation} score={row.fit_score} />
              </TableCell>
              <TableCell>
                <InterviewStatusBadge status={row.status as InterviewStatus} />
              </TableCell>
              <TableCell>
                {row.decision ? (
                  <Badge variant={row.decision === "reject" ? "destructive" : "outline"}>
                    {DECISION_LABELS[row.decision as Decision] ?? row.decision}
                  </Badge>
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {row.evaluated_at ? new Date(row.evaluated_at).toLocaleDateString("ru-RU") : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
