"use client";

import { useParams } from "next/navigation";
import { createRef, useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { AnswerPlayer, type AnswerPlayerHandle } from "@/components/reports/answer-player";
import { DecisionPanel } from "@/components/reports/decision-panel";
import { EvaluationView, RecommendationBadge } from "@/components/reports/evaluation-view";
import { NotesPanel } from "@/components/reports/notes-panel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import { publicReportsApi, type Decision, type PublicReport } from "@/lib/api/reports";

export default function SharedReportPage() {
  const params = useParams<{ token: string }>();
  const { toast } = useToast();
  const [report, setReport] = useState<PublicReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const playerRefs = useRef<Map<string, React.RefObject<AnswerPlayerHandle>>>(new Map());

  const load = useCallback(async () => {
    try {
      setReport(await publicReportsApi.get(params.token));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Отчёт недоступен");
    }
  }, [params.token]);

  useEffect(() => {
    void load();
  }, [load]);

  const refFor = (answerId: string) => {
    let ref = playerRefs.current.get(answerId);
    if (!ref) {
      ref = createRef<AnswerPlayerHandle>();
      playerRefs.current.set(answerId, ref);
    }
    return ref;
  };

  const seek = (answerId: string, seconds: number | null) => {
    playerRefs.current.get(answerId)?.current?.seek(seconds ?? 0);
  };

  const decide = async (decision: Decision, note: string) => {
    try {
      await publicReportsApi.decide(params.token, { decision, note });
      toast({ title: "Решение сохранено" });
      setReport((current) => (current ? { ...current, decision, decision_note: note } : current));
    } catch (caught) {
      toast({ variant: "destructive", title: caught instanceof ApiError ? caught.message : "Не удалось сохранить решение" });
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
          <Logo size={28} />
          {report ? <span className="text-sm text-muted-foreground">{report.organization_name}</span> : null}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        {error ? (
          <div className="text-center">
            <h1 className="text-xl font-bold">Отчёт недоступен</h1>
            <p className="mt-2 text-sm text-muted-foreground">{error}</p>
          </div>
        ) : !report ? (
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        ) : (
          <>
            <p className="text-sm text-muted-foreground">{report.vacancy_title}</p>
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <h1 className="text-2xl font-bold tracking-tight">{report.candidate_name}</h1>
              <RecommendationBadge value={report.evaluation?.recommendation ?? null} score={report.evaluation?.fit_score ?? null} />
            </div>
            <Tabs defaultValue="answers">
              <TabsList className="mb-4 flex-wrap">
                <TabsTrigger value="answers">Ответы ({report.answers.length})</TabsTrigger>
                <TabsTrigger value="evaluation">Заключение</TabsTrigger>
                <TabsTrigger value="decision">Решение и заметки</TabsTrigger>
              </TabsList>
              <TabsContent value="answers" className="space-y-4">
                {report.answers.map((answer) => (
                  <Card key={answer.id}>
                    <CardHeader>
                      <CardTitle className="text-base">
                        {answer.question_index + 1}. {answer.question_text}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <AnswerPlayer
                        ref={refFor(answer.id)}
                        src={answer.media_url}
                        contentType={answer.media_content_type}
                        segments={answer.transcript_segments}
                        transcript={answer.transcript_text}
                      />
                    </CardContent>
                  </Card>
                ))}
              </TabsContent>
              <TabsContent value="evaluation">
                {report.evaluation?.output ? (
                  <EvaluationView output={report.evaluation.output} onSeek={seek} />
                ) : (
                  <p className="text-sm text-muted-foreground">Заключение готовится.</p>
                )}
              </TabsContent>
              <TabsContent value="decision" className="space-y-4">
                <DecisionPanel decision={report.decision} note={report.decision_note} disabled={!report.can_decide} onDecide={decide} />
                <NotesPanel
                  notes={report.notes}
                  canWrite={report.can_note}
                  onAdd={async (text) => {
                    try {
                      const note = await publicReportsApi.addNote(params.token, { text });
                      setReport((current) => (current ? { ...current, notes: [...current.notes, note] } : current));
                    } catch (caught) {
                      toast({ variant: "destructive", title: caught instanceof ApiError ? caught.message : "Не удалось добавить заметку" });
                    }
                  }}
                  onSeek={seek}
                />
              </TabsContent>
            </Tabs>
            <p className="mt-8 text-xs text-muted-foreground">
              Ссылка действует до {new Date(report.expires_at).toLocaleDateString("ru-RU")}. Решение по кандидату принимает человек; рекомендация модели — подсказка.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
