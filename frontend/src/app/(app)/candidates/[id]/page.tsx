"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { InterviewStatusBadge } from "@/components/candidates/status-badge";
import { HhDialogCard } from "@/components/integrations/hh-dialog";
import { HuntflowPush } from "@/components/integrations/huntflow-push";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { candidatesApi, type Candidate, type Interview } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";

export default function CandidatePage() {
  const params = useParams<{ id: string }>();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [interviews, setInterviews] = useState<Interview[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, list] = await Promise.all([candidatesApi.get(params.id), candidatesApi.interviews(params.id)]);
      setCandidate(c);
      setInterviews(list);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить кандидата");
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <p className="text-destructive">{error}</p>;
  if (!candidate) return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;

  return (
    <>
      <PageHeader title={candidate.full_name} description={candidate.email} actions={<HuntflowPush candidateId={candidate.id} />} />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Интервью</CardTitle>
          </CardHeader>
          <CardContent>
            {interviews.length === 0 ? (
              <p className="text-sm text-muted-foreground">Приглашений ещё не было.</p>
            ) : (
              <ul className="divide-y">
                {interviews.map((interview) => (
                  <li key={interview.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                    <div>
                      <Link
                        href={`/vacancies/${interview.vacancy_id}/interviews/${interview.id}`}
                        className="font-medium hover:underline"
                      >
                        {interview.vacancy_title}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        приглашён {new Date(interview.invited_at).toLocaleDateString("ru-RU")}
                        {interview.completed_at
                          ? ` · завершил ${new Date(interview.completed_at).toLocaleDateString("ru-RU")}`
                          : ""}
                      </div>
                    </div>
                    <InterviewStatusBadge status={interview.status} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Карточка</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              <span className="text-muted-foreground">Телефон: </span>
              {candidate.phone ?? "—"}
            </p>
            <p>
              <span className="text-muted-foreground">Источник: </span>
              {candidate.source}
            </p>
            <p>
              <span className="text-muted-foreground">Рассылка: </span>
              {candidate.newsletter_opt_in ? "согласен(на)" : "нет"}
            </p>
            {candidate.notes ? <p className="whitespace-pre-wrap">{candidate.notes}</p> : null}
          </CardContent>
        </Card>
        <HhDialogCard candidateId={candidate.id} />
      </div>
    </>
  );
}
