"use client";

import { RowsSkeleton, Skeleton } from "@/components/ui/skeleton";

import Link from "@/lib/router";
import { useParams } from "@/lib/router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Clock3, Mail, RefreshCw, Video } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { InterviewStatusBadge } from "@/components/candidates/status-badge";
import { AnswerPlayer, type AnswerPlayerHandle } from "@/components/reports/answer-player";
import { CodeSubmission } from "@/components/reports/code-submission";
import { DecisionPanel } from "@/components/reports/decision-panel";
import { EvaluationView, RecommendationBadge } from "@/components/reports/evaluation-view";
import { IntegrityPanel } from "@/components/reports/integrity-panel";
import { NotesPanel } from "@/components/reports/notes-panel";
import { SharePanel } from "@/components/reports/share-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { interviewsApi, type Interview } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";
import {
  reportsApi,
  type AnswerDetail,
  type Decision,
  type Evaluation,
  type IntegrityReport,
  DECISION_LABELS,
  type Note,
} from "@/lib/api/reports";

const PROCESSING_STATUSES = new Set(["completed", "processing"]);

export default function InterviewReportPage() {
  const params = useParams<{ id: string; interviewId: string }>();
  const { me, can } = useAuth();
  const { toast } = useToast();
  const [interview, setInterview] = useState<Interview | null>(null);
  const [answers, setAnswers] = useState<AnswerDetail[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [integrity, setIntegrity] = useState<IntegrityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRequest = useRef(0);
  const [sectionErrors, setSectionErrors] = useState({ evaluation: false, integrity: false });
  const playerRef = useRef<AnswerPlayerHandle | null>(null);
  const [tab, setTab] = useState("evaluation");
  const [selectedAnswerId, setSelectedAnswerId] = useState<string | null>(null);
  const [seekRequest, setSeekRequest] = useState<{ answerId: string; seconds: number } | null>(null);
  const [reprocessing, setReprocessing] = useState(false);
  const activeAnswer = answers.find(answer => answer.id === selectedAnswerId) ?? answers[0];

  const fail = useCallback(
    (caught: unknown, fallback: string) =>
      toast({ variant: "destructive", title: caught instanceof ApiError ? caught.message : fallback }),
    [toast],
  );

  const load = useCallback(async () => {
    const sequence = ++loadRequest.current;
    try {
      const [i, a, n] = await Promise.all([
        interviewsApi.get(params.interviewId),
        reportsApi.answers(params.interviewId),
        reportsApi.notes(params.interviewId),
      ]);
      if (sequence !== loadRequest.current) return;
      setError(null);
      setInterview(i);
      setAnswers(a.filter((answer) => answer.is_final));
      setNotes(n);
      try {
        const value = await reportsApi.evaluation(params.interviewId);
        if (sequence !== loadRequest.current) return;
        setEvaluation(value); setSectionErrors(current => ({ ...current, evaluation: false }));
      } catch (caught) {
        if (sequence !== loadRequest.current) return;
        setEvaluation(null); setSectionErrors(current => ({ ...current, evaluation: !(caught instanceof ApiError && caught.status === 404) }));
      }
      try {
        const value = await reportsApi.integrity(params.interviewId);
        if (sequence !== loadRequest.current) return;
        setIntegrity(value); setSectionErrors(current => ({ ...current, integrity: false }));
      } catch (caught) {
        if (sequence !== loadRequest.current) return;
        setIntegrity(null); setSectionErrors(current => ({ ...current, integrity: !(caught instanceof ApiError && caught.status === 404) }));
      }
    } catch (caught) {
      if (sequence === loadRequest.current) setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить интервью");
    }
  }, [params.interviewId]);

  useEffect(() => {
    setInterview(null); setEvaluation(null); setIntegrity(null); setError(null);
    setSelectedAnswerId(null); setSeekRequest(null); setTab("evaluation");
    void load();
    return () => { loadRequest.current++; };
  }, [load]);

  // Пока идёт обработка — опрашиваем раз в 10 с, отчёт открывается с частичными данными.
  useEffect(() => {
    if (!interview || !PROCESSING_STATUSES.has(interview.status)) return;
    const timer = setInterval(() => void load(), 10000);
    return () => clearInterval(timer);
  }, [interview, load]);

  const seek = useCallback((answerId: string, seconds: number | null) => {
    setSelectedAnswerId(answerId); setTab("answers"); setSeekRequest({ answerId, seconds: seconds ?? 0 });
  }, []);
  useEffect(() => {
    if (tab !== "answers" || !seekRequest || activeAnswer?.id !== seekRequest.answerId) return;
    playerRef.current?.seek(seekRequest.seconds);
    const detail = document.getElementById(`answer-${seekRequest.answerId}`);
    detail?.focus({ preventScroll: true });
    detail?.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    setSeekRequest(null);
  }, [tab, activeAnswer?.id, seekRequest]);

  const decide = async (decision: Decision, note: string) => {
    try {
      setInterview(await reportsApi.decide(params.interviewId, { decision, note }));
      toast({ title: "Решение сохранено", celebrate: decision === "advance" && interview?.decision !== "advance" });
    } catch (caught) {
      fail(caught, "Не удалось сохранить решение");
    }
  };

  const reprocess = async () => {
    setReprocessing(true);
    try {
      await reportsApi.reprocess(params.interviewId);
      toast({ title: "Обработка запущена заново" });
      await load();
    } catch (caught) {
      fail(caught, "Не удалось перезапустить обработку");
    } finally { setReprocessing(false); }
  };

  const processingCount = useMemo(
    () => answers.filter((a) => a.status === "uploaded" || a.status === "processing").length,
    [answers],
  );

  if (error) return <div className="report-empty" role="alert"><h2>Не удалось открыть интервью</h2><p>{error}</p><Button variant="outline" onClick={() => void load()}>Попробовать снова</Button></div>;
  if (!interview) return <RowsSkeleton />;
  const duration = Math.round(answers.reduce((sum, answer) => sum + (answer.duration_ms ?? 0), 0) / 60000);

  return (
    <div className="report-workspace">
      <Link href={`/vacancies/${params.id}?tab=candidates`} className="report-back"><ArrowLeft size={17} />{interview.vacancy_title}</Link>
      <header className="report-heading"><div className="report-person"><div className="report-avatar" aria-hidden>{interview.candidate_name.split(" ").slice(0, 2).map(part => part[0]).join("")}</div><div><h1>{interview.candidate_name}</h1><a href={`mailto:${interview.candidate_email}`}><Mail size={15} />{interview.candidate_email}</a><div className="report-meta"><InterviewStatusBadge status={interview.status} /><span><Video size={15} />Ответов: {answers.length}</span>{duration > 0 && <span><Clock3 size={15} />{duration} мин</span>}</div></div></div>
        <div className="report-outcome">{evaluation?.fit_score !== null && evaluation?.fit_score !== undefined && <div className="report-fit-score"><strong>{Math.round(evaluation.fit_score)}</strong><span>из 100</span></div>}<RecommendationBadge value={evaluation?.recommendation ?? null} score={null} /></div>
      </header>
      <div className="report-toolbar"><span>{interview.completed_at ? `Интервью от ${new Date(interview.completed_at).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}` : "Интервью ещё не завершено"}{interview.decision && ` · Решение: ${DECISION_LABELS[interview.decision as Decision] ?? interview.decision}`}</span>{can("candidate.write") && <Button variant="ghost" size="sm" onClick={reprocess} disabled={reprocessing}><RefreshCw size={16} />{reprocessing ? "Запускаем…" : "Обновить анализ"}</Button>}</div>
      {(processingCount > 0 || evaluation?.status === "pending") && <div className="report-processing"><Skeleton className="h-5 w-5 rounded-md" /><span>Леон разбирает ответы. Отчёт обновится автоматически.</span></div>}
      {evaluation?.status === "failed" && <div className="report-processing text-destructive" role="alert">Не удалось подготовить оценку: {evaluation.error ?? "ошибка обработки"}. Попробуйте обновить анализ.</div>}
      <Tabs value={tab} onValueChange={setTab} className="report-tabs">
        <TabsList><TabsTrigger value="evaluation">Отчёт</TabsTrigger><TabsTrigger value="answers">Ответы <span className="report-tab-count">{answers.length}</span></TabsTrigger><TabsTrigger value="integrity">Проверка записи{integrity && integrity.flags > 0 ? ` · ${integrity.flags}` : ""}</TabsTrigger><TabsTrigger value="decision">Решение и заметки</TabsTrigger>{can("report.share") && <TabsTrigger value="share">Доступ</TabsTrigger>}</TabsList>
        <TabsContent value="answers">
          {!activeAnswer ? <div className="report-empty"><Video size={30} /><h2>Ответов пока нет</h2><p>Они появятся здесь после записи кандидатом.</p></div> : <div className="report-answers-layout"><nav className="report-question-nav" aria-label="Вопросы интервью">{answers.map((answer, index) => <button key={answer.id} className="report-question-option" aria-current={activeAnswer.id === answer.id ? "true" : undefined} onClick={() => setSelectedAnswerId(answer.id)}><span className="report-question-number">{String(index + 1).padStart(2, "0")}</span><span><strong>{answer.question_text || `Вопрос ${answer.question_index + 1}`}</strong><small>{answer.duration_ms ? `${Math.floor(answer.duration_ms / 60000)}:${String(Math.floor(answer.duration_ms / 1000) % 60).padStart(2, "0")}` : "Ответ записан"}{answer.attempt > 1 ? ` · попытка ${answer.attempt}` : ""}</small></span></button>)}</nav>
            <section className="report-answer-detail" tabIndex={-1} id={`answer-${activeAnswer.id}`}><header><span>Вопрос {activeAnswer.question_index + 1} из {interview.question_count ?? answers.length}</span><h2>{activeAnswer.question_text || "Ответ кандидата"}</h2></header>
              {activeAnswer.code_submission && <CodeSubmission submission={activeAnswer.code_submission} className="report-code" />}
              {(!activeAnswer.code_submission || activeAnswer.media_url) && <AnswerPlayer key={activeAnswer.id} ref={playerRef} src={activeAnswer.media_url} contentType={activeAnswer.media_content_type} segments={activeAnswer.transcript_segments} transcript={activeAnswer.transcript_text} />}
              {activeAnswer.status === "failed" && <p className="report-notice text-destructive">Обработка не удалась: {activeAnswer.processing_error}</p>}
              <footer className="report-answer-navigation"><Button variant="ghost" disabled={answers.indexOf(activeAnswer) === 0} onClick={() => setSelectedAnswerId(answers[answers.indexOf(activeAnswer) - 1].id)}><ArrowLeft size={17} />Назад</Button><Button variant="outline" disabled={answers.indexOf(activeAnswer) === answers.length - 1} onClick={() => setSelectedAnswerId(answers[answers.indexOf(activeAnswer) + 1].id)}>Следующий<ArrowRight size={17} /></Button></footer>
            </section></div>}
        </TabsContent>

        <TabsContent value="integrity">
          {sectionErrors.integrity ? <div className="report-empty" role="alert"><p>Не удалось загрузить проверку записи.</p><Button variant="outline" onClick={() => void load()}>Повторить</Button></div> : <IntegrityPanel
            report={integrity}
            readOnly={!can("report.decide")}
            onReview={async (observation, verdict) => {
              try {
                setIntegrity(
                  await reportsApi.reviewIntegrity(params.interviewId, {
                    code: observation.code,
                    question_index: observation.question_index,
                    verdict,
                  }),
                );
              } catch (caught) {
                fail(caught, "Не удалось сохранить решение по наблюдению");
              }
            }}
          />}
        </TabsContent>

        <TabsContent value="evaluation">
          {sectionErrors.evaluation ? <div className="report-empty" role="alert"><p>Не удалось загрузить отчёт.</p><Button variant="outline" onClick={() => void load()}>Повторить</Button></div> : evaluation?.output ? (
            <EvaluationView output={evaluation.output} onSeek={seek} />
          ) : (
            <p className="report-empty">
              {interview.status === "in_progress" || interview.status === "consented" || interview.status === "invited" || interview.status === "opened"
                ? "Заключение появится после завершения интервью."
                : "Заключение готовится."}
            </p>
          )}
          {evaluation?.candidate_feedback && can("candidate.write") ? (
            <Card className="report-feedback mt-5">
              <CardHeader>
                <CardTitle className="text-base">Обратная связь кандидату</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-base">
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

        <TabsContent value="decision" className="report-decision-grid">
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
                const note = await reportsApi.addNote(params.interviewId, { text });
                setNotes(current => [...current, note]);
              } catch (caught) {
                fail(caught, "Не удалось добавить заметку");
                return false;
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
    </div>
  );
}
