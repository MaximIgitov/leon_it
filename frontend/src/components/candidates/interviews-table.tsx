"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, XCircle } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { CopyField, InviteDialog } from "@/components/candidates/invite-dialog";
import { InterviewStatusBadge } from "@/components/candidates/status-badge";
import { RecommendationBadge } from "@/components/reports/evaluation-view";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { interviewsApi, type Interview } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";
import { DECISION_LABELS, type Decision, type Recommendation } from "@/lib/api/reports";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

const OPEN_STATUSES = new Set(["invited", "opened", "consented", "in_progress", "expired"]);
/** Интервью пройдено: заключение либо готово, либо готовится. */
const AWAITING_STATUSES = new Set(["completed", "processing"]);

/** Балл, рекомендация, уверенность и цитаты — чтобы список был рабочим без перехода в карточку. */
function ScoreCell({ interview }: { interview: Interview }) {
  if (interview.recommendation) {
    return (
      <div className="space-y-1">
        <RecommendationBadge value={interview.recommendation as Recommendation} score={interview.fit_score ?? null} />
        <div className="text-xs text-muted-foreground">
          {typeof interview.confidence === "number" ? `уверенность ${Math.round(interview.confidence * 100)} %` : null}
          {typeof interview.confidence === "number" && interview.quotes_total ? " · " : null}
          {interview.quotes_total ? `цитаты ${interview.quotes_found ?? 0}/${interview.quotes_total}` : null}
        </div>
      </div>
    );
  }
  if (AWAITING_STATUSES.has(interview.status)) return <RecommendationBadge value={null} score={null} />;
  return <span className="text-sm text-muted-foreground">—</span>;
}

export function InterviewsTable({ vacancyId, showVacancy = false }: { vacancyId?: string; showVacancy?: boolean }) {
  const { can } = useAuth();
  const { toast } = useToast();
  const [items, setItems] = useState<Interview[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [freshLink, setFreshLink] = useState<{ id: string; link: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await interviewsApi.list(vacancyId));
    } catch (error) {
      toast({ variant: "destructive", title: error instanceof ApiError ? error.message : "Не удалось загрузить интервью" });
    }
  }, [vacancyId, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (id: string, action: () => Promise<Interview>) => {
    setBusy(id);
    try {
      const updated = await action();
      setItems((current) => current?.map((i) => (i.id === updated.id ? { ...updated, link: null } : i)) ?? null);
      if (updated.link) setFreshLink({ id: updated.id, link: updated.link });
    } catch (error) {
      toast({ variant: "destructive", title: error instanceof ApiError ? error.message : "Действие не выполнено" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      {can("candidate.write") ? (
        <div className="flex justify-end">
          <InviteDialog vacancyId={vacancyId} onInvited={() => void load()} />
        </div>
      ) : null}
      {freshLink ? (
        <div className="rounded-lg border bg-muted/40 p-3 text-sm">
          <p className="mb-2">Новая ссылка (показывается один раз):</p>
          <CopyField value={freshLink.link} />
        </div>
      ) : null}
      {items === null ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          Приглашений пока нет.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Кандидат</TableHead>
                {showVacancy ? <TableHead>Вакансия</TableHead> : null}
                <TableHead>Статус</TableHead>
                <TableHead>Оценка</TableHead>
                <TableHead>Решение</TableHead>
                <TableHead>Приглашён</TableHead>
                <TableHead>До</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((interview) => (
                <TableRow key={interview.id}>
                  <TableCell>
                    <Link
                      href={`/vacancies/${interview.vacancy_id}/interviews/${interview.id}`}
                      className="font-medium hover:underline"
                    >
                      {interview.candidate_name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{interview.candidate_email}</div>
                  </TableCell>
                  {showVacancy ? (
                    <TableCell>
                      <Link href={`/vacancies/${interview.vacancy_id}`} className="hover:underline">
                        {interview.vacancy_title}
                      </Link>
                    </TableCell>
                  ) : null}
                  <TableCell>
                    <InterviewStatusBadge status={interview.status} />
                  </TableCell>
                  <TableCell>
                    <ScoreCell interview={interview} />
                  </TableCell>
                  <TableCell className="text-sm">
                    {interview.decision ? (DECISION_LABELS[interview.decision as Decision] ?? interview.decision) : "—"}
                  </TableCell>
                  <TableCell className="text-sm">{formatDate(interview.invited_at)}</TableCell>
                  <TableCell className="text-sm">{formatDate(interview.expires_at)}</TableCell>
                  <TableCell className="text-right">
                    {can("candidate.write") && OPEN_STATUSES.has(interview.status) ? (
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy === interview.id}
                          onClick={() => run(interview.id, () => interviewsApi.resend(interview.id))}
                          title="Новая ссылка и повторное письмо"
                        >
                          <RefreshCw className="mr-1 h-4 w-4" />
                          Переслать
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy === interview.id}
                          onClick={() => run(interview.id, () => interviewsApi.cancel(interview.id))}
                        >
                          <XCircle className="mr-1 h-4 w-4" />
                          Отменить
                        </Button>
                      </div>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
