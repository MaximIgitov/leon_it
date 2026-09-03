"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { createRef, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { InterviewStatusBadge } from "@/components/candidates/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { AnswerPlayer, type AnswerPlayerHandle } from "@/components/reports/answer-player";
import { DecisionPanel } from "@/components/reports/decision-panel";
import { EvaluationView, RecommendationBadge } from "@/components/reports/evaluation-view";
import { NotesPanel } from "@/components/reports/notes-panel";
import { SharePanel } from "@/components/reports/share-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { interviewsApi, type Interview } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";
import { reportsApi, type AnswerDetail, type Decision, type Evaluation, type Note } from "@/lib/api/reports";

const PROCESSING_STATUSES = new Set(["completed", "processing"]);

export default function InterviewReportPage() {
  const params = useParams<{ id: string; interviewId: string }>();
  const { me, can } = useAuth();
  const { toast } = useToast();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [answers, setAnswers] = useState<AnswerDetail[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [error, setError] = useState<string | null>(null);
  const playerRefs = useRef<Map<string, React.RefObject<AnswerPlayerHandle>>>(new Map());

  const fail = useCallback(
    (caught: unknown, fallback: string) =>
      toast({ variant: "destructive", title: caught instanceof ApiError ? caught.message : fallback }),
    [toast],
  );

  const load = useCallback(async () => {
    try {
      const [i, a, n] = await Promise.all([
        interviewsApi.get(params.interviewId),
        reportsApi.answers(params.interviewId),
        reportsApi.notes(params.interviewId),
      ]);
      setInterview(i);
      setAnswers(a.filter((answer) => answer.is_final));
      setNotes(n);
      try {
        setEvaluation(await reportsApi.evaluation(params.interviewId));
      } catch {
        setEvaluation(null);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить интервью");
    }
  }, [params.interviewId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Пока идёт обработка — опрашиваем раз в 10 с, отчёт открывается с частичными данными.
  useEffect(() => {
    if (!interview || !PROCESSING_STATUSES.has(interview.status)) return;
    const timer = setInterval(() => void load(), 10000);
    return () => clearInterval(timer);
  }, [interview, load]);

  const seek = useCallback((answerId: string, seconds: number | null) => {
    playerRefs.current.get(answerId)?.current?.seek(seconds ?? 0);
  }, []);

  const refFor = (answerId: string) => {
    let ref = playerRefs.current.get(answerId);
    if (!ref) {
      ref = createRef<AnswerPlayerHandle>();
      playerRefs.current.set(answerId, ref);
    }
    return ref;
  };

  const decide = async (decision: Decision, note: string) => {
    try {
      setInterview(await reportsApi.decide(params.interviewId, { decision, note }));
      toast({ title: "Решение сохранено" });
    } catch (caught) {
      fail(caught, "Не удалось сохранить решение");
    }
  };

  const reprocess = async () => {
    try {
      await reportsApi.reprocess(params.interviewId);
      toast({ title: "Обработка запущена заново" });
      await load();
    } catch (caught) {
      fail(caught, "Не удалось перезапустить обработку");
    }
  };

  const processingCount = useMemo(
    () => answers.filter((a) => a.status === "uploaded" || a.status === "processing").length,
    [answers],
  );

  if (error) return <p className="text-destructive">{error}</p>;
  if (!interview) return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;

  return (
    <>
      <div className="mb-2">
        <Button variant="ghost" size="sm" asChild>
          <Link href={`/vacancies/${params.id}`}>
            <ArrowLeft className="mr-2 h-4 w-4" /> {interview.vacancy_title}
          </Link>
        </Button>
      </div>
      <PageHeader
        title={interview.candidate_name}
        description={interview.candidate_email}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <InterviewStatusBadge status={interview.status} />
            <RecommendationBadge value={evaluation?.recommendation ?? null} score={evaluation?.fit_score ?? null} />
            {can("candidate.write") ? (
              <Button variant="outline" size="sm" onClick={reprocess}>
                <RefreshCw className="mr-2 h-4 w-4" /> Переобработать
              </Button>
            ) : null}
          </div>
        }
      />

      {processingCount > 0 || (evaluation && evaluation.status === "pending") ? (
        <p className="mb-4 flex items-center gap-2 rounded-lg border bg-muted/40 p-3 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          Идёт обработка: видео уже доступно, транскрипт и заключение появятся через несколько минут.
        </p>
      ) : null}
      {evaluation?.status === "failed" ? (
        <p className="mb-4 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm">
          Оценка не удалась: {evaluation.error ?? "неизвестная ошибка"}. Нажмите «Переобработать».
        </p>
      ) : null}

      <Tabs defaultValue="answers">
        <TabsList className="mb-4 flex-wrap">
          <TabsTrigger value="answers">Ответы ({answers.length})</TabsTrigger>
          <TabsTrigger value="evaluation">Заключение</TabsTrigger>
          <TabsTrigger value="decision">Решение и заметки</TabsTrigger>
          {can("report.share") ? <TabsTrigger value="share">Доступ</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="answers" className="space-y-4">
          {answers.length === 0 ? (
            <p className="text-sm text-muted-foreground">Кандидат ещё не записал ответы.</p>
          ) : (
            answers.map((answer) => (
              <Card key={answer.id} id={`answer-${answer.id}`}>
                <CardHeader>
                  <CardTitle className="text-base">
                    {answer.question_index + 1}. {answer.question_text}
                    {answer.attempt > 1 ? (
                      <span className="ml-2 text-xs font-normal text-muted-foreground">попытка {answer.attempt}</span>
                    ) : null}
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
                  {answer.status === "failed" ? (
                    <p className="mt-2 text-xs text-destructive">Обработка не удалась: {answer.processing_error}</p>
                  ) : null}
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="evaluation">
          {evaluation?.output ? (
            <EvaluationView output={evaluation.output} onSeek={seek} />
          ) : (
            <p className="text-sm text-muted-foreground">
              {interview.status === "in_progress" || interview.status === "consented" || interview.status === "invited" || interview.status === "opened"
                ? "Заключение появится после завершения интервью."
                : "Заключение готовится."}
            </p>
          )}
          {evaluation?.candidate_feedback && can("candidate.write") ? (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle className="text-base">Обратная связь кандидату (превью)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>{evaluation.candidate_feedback.greeting}</p>
                <ul className="list-disc pl-5">
                  {evaluation.candidate_feedback.strengths.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
                <ul className="list-disc pl-5">
                  {evaluation.candidate_feedback.suggestions.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
                <p>{evaluation.candidate_feedback.closing}</p>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>

        <TabsContent value="decision" className="space-y-4">
          <DecisionPanel
            decision={interview.decision}
            note={null}
            disabled={!can("report.decide") || !["completed", "processing", "evaluated", "reviewed", "advanced", "rejected"].includes(interview.status)}
            onDecide={decide}
          />
          <NotesPanel
            notes={notes}
            canWrite={can("report.decide")}
            currentUserId={me?.id}
            onAdd={async (text) => {
              try {
                await reportsApi.addNote(params.interviewId, { text });
                setNotes(await reportsApi.notes(params.interviewId));
              } catch (caught) {
                fail(caught, "Не удалось добавить заметку");
              }
            }}
            onDelete={async (noteId) => {
              try {
                await reportsApi.deleteNote(params.interviewId, noteId);
                setNotes((current) => current.filter((n) => n.id !== noteId));
              } catch (caught) {
                fail(caught, "Не удалось удалить заметку");
              }
            }}
            onSeek={seek}
          />
        </TabsContent>

        {can("report.share") ? (
          <TabsContent value="share">
            <SharePanel interviewId={params.interviewId} />
          </TabsContent>
        ) : null}
      </Tabs>
    </>
  );
}
