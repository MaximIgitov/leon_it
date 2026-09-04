"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Loader2, Mic, RotateCcw, Square, Video } from "lucide-react";

import { AvatarStage } from "@/components/interview/avatar-stage";
import { CodeEditor, clearDraft, draftStorageKey, type CodeDraft } from "@/components/interview/code-editor";
import { CodeSubmission } from "@/components/reports/code-submission";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useFaceWatch } from "@/hooks/use-face-watch";
import { useInterviewTelemetry } from "@/hooks/use-interview-telemetry";
import { ApiError, API_BASE_URL } from "@/lib/api/client";
import { roomApi, type AvatarInfo, type InterviewState, type RoomAnswer, type SnapshotQuestion } from "@/lib/api/room";
import { AnswerRecorder, type UploadProgress } from "@/lib/media/recorder";
import type { DeviceCheckResult } from "@/components/interview/device-check";

type Phase = "loading" | "intro" | "prep" | "coding" | "recording" | "uploading" | "review" | "done" | "error";

// Автосохранение черновика кода на сервер: не чаще, чем раз в пару секунд после паузы.
const DRAFT_SAVE_DELAY_MS = 2500;

function formatSeconds(total: number): string {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function attemptsUsed(state: InterviewState, index: number): number {
  return state.answers.filter((a) => a.question_index === index && a.status !== "abandoned").length;
}

/** Попытки с видео: попытка, где лежит только код, записи не занимает. */
function explanationAttempts(state: InterviewState, index: number): number {
  return state.answers.filter(
    (a) => a.question_index === index && a.status !== "abandoned" && !(a.code_submission && a.media_size === 0),
  ).length;
}

function hasUploaded(state: InterviewState, index: number): boolean {
  return state.answers.some((a) => a.question_index === index && a.status !== "recording" && a.status !== "abandoned");
}

function latestCodeAnswer(state: InterviewState, index: number): RoomAnswer | null {
  const rows = state.answers.filter((a) => a.question_index === index && a.status !== "abandoned" && a.code_submission);
  if (rows.length === 0) return null;
  return rows.reduce((best, a) => (a.attempt > best.attempt ? a : best));
}

function isAnswered(state: InterviewState, question: SnapshotQuestion): boolean {
  if (question.kind === "code") return Boolean(latestCodeAnswer(state, question.index)?.code_submission?.submitted_at);
  return hasUploaded(state, question.index);
}

export function InterviewRoom({
  token,
  devices,
  onFinished,
}: {
  token: string;
  devices: DeviceCheckResult;
  onFinished: () => void;
}) {
  const [state, setState] = useState<InterviewState | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [question, setQuestion] = useState<SnapshotQuestion | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [avatar, setAvatar] = useState<AvatarInfo | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resumed, setResumed] = useState(false);
  const [codeBusy, setCodeBusy] = useState<"submit" | "run" | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const recorderRef = useRef<AnswerRecorder | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<number | null>(null);
  const draftTimerRef = useRef<number | null>(null);
  const wakeLock = useRef<{ release: () => Promise<void> } | null>(null);

  const index = state?.current_question_index ?? 0;
  const total = state?.total_questions ?? 0;
  const getContext = useCallback(
    () => ({ questionIndex: index, answerId: recorderRef.current?.id ?? undefined }),
    [index],
  );
  const telemetry = useInterviewTelemetry(token, getContext, phase !== "loading" && phase !== "done");

  // Сколько лиц в кадре: считается локально во время записи, наружу уходит
  // только число (см. use-face-watch).
  useFaceWatch(videoRef.current, phase === "recording", (count) =>
    telemetry.push("faces", { count }),
  );

  // Превью камеры на протяжении всей комнаты.
  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.srcObject = devices.stream;
      void video.play().catch(() => undefined);
    }
  }, [devices.stream, phase]);

  // На мобильных не даём экрану погаснуть во время записи.
  useEffect(() => {
    const nav = navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<{ release: () => Promise<void> }> } };
    if (!devices.environment.mobile || !nav.wakeLock) return;
    nav.wakeLock.request("screen").then((lock) => (wakeLock.current = lock)).catch(() => undefined);
    return () => {
      void wakeLock.current?.release().catch(() => undefined);
    };
  }, [devices.environment.mobile]);

  const fail = useCallback((caught: unknown, fallback: string) => {
    setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : fallback);
    setPhase("error");
  }, []);

  // Старт или продолжение.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const clientInfo = {
          user_agent: devices.environment.userAgent,
          browser: devices.environment.browser,
          platform: devices.environment.platform,
          mobile: devices.environment.mobile,
          screen: typeof window !== "undefined" ? `${window.screen.width}x${window.screen.height}` : null,
          devices: devices.devices.map((d) => ({ kind: d.kind, label: d.label })),
          virtual_camera: devices.virtualCamera,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        };
        const next = await roomApi.start(token, clientInfo);
        if (cancelled) return;
        setState(next);
        if (next.status === "completed") {
          setPhase("done");
          return;
        }
        setResumed(next.answers.length > 0 || next.current_question_index > 0);
        setPhase("intro");
        telemetry.push("devices_enumerated", { devices: clientInfo.devices, virtual_camera: devices.virtualCamera });
      } catch (caught) {
        if (!cancelled) fail(caught, "Не удалось начать интервью");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const clearTimer = () => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const clearDraftTimer = () => {
    if (draftTimerRef.current) {
      window.clearTimeout(draftTimerRef.current);
      draftTimerRef.current = null;
    }
  };

  useEffect(() => () => clearDraftTimer(), []);

  const replayQuestion = () => {
    if (audioRef.current && audioUrl) void audioRef.current.play().catch(() => undefined);
  };

  /** Показать вопрос: озвучка и отсчёт подготовки стартуют в одном клике (iOS). */
  const showQuestion = async () => {
    if (!state) return;
    try {
      const revealed = await roomApi.reveal(token, index);
      setQuestion(revealed.question);
      setAvatar(revealed.avatar);
      const url = revealed.audio_url ? `${API_BASE_URL.replace(/\/api$/, "")}${revealed.audio_url}` : null;
      setAudioUrl(url);
      // Если аватар произносит вопрос сам, вторую озвучку поверх не запускаем.
      const avatarSpeaks = Boolean(revealed.avatar?.enabled && revealed.avatar.clip_url);
      if (url && audioRef.current && !avatarSpeaks) {
        audioRef.current.src = url;
        void audioRef.current.play().catch(() => undefined);
      }
      if (revealed.question.kind === "code") {
        // Секция кода: без таймера подготовки и записи — сначала решение, пояснение по желанию.
        setCodeError(null);
        setPhase("coding");
        return;
      }
      setPhase("prep");
      setCountdown(revealed.question.prep_seconds);
      if (revealed.question.prep_seconds > 0) {
        clearTimer();
        timerRef.current = window.setInterval(() => {
          setCountdown((value) => {
            if (value <= 1) {
              clearTimer();
              void startRecording(revealed.question);
              return 0;
            }
            return value - 1;
          });
        }, 1000);
      } else {
        void startRecording(revealed.question);
      }
    } catch (caught) {
      fail(caught, "Не удалось получить вопрос");
    }
  };

  const startRecording = async (current: SnapshotQuestion) => {
    clearTimer();
    audioRef.current?.pause();
    setProgress(null);
    const recorder = new AnswerRecorder({
      token,
      questionIndex: current.index,
      stream: devices.stream,
      onProgress: setProgress,
      onError: (err) => telemetry.push("recorder_error", { message: err.message }),
    });
    recorderRef.current = recorder;
    try {
      await recorder.start();
      telemetry.push("recorder_started", { mime_type: recorder.mimeType });
      setPhase("recording");
      setElapsed(0);
      timerRef.current = window.setInterval(() => {
        setElapsed((value) => {
          const next = value + 1;
          if (next >= current.max_answer_seconds) {
            clearTimer();
            void stopRecording();
          }
          return next;
        });
      }, 1000);
    } catch (caught) {
      fail(caught, "Не удалось начать запись");
    }
  };

  const stopRecording = async () => {
    clearTimer();
    const recorder = recorderRef.current;
    if (!recorder) return;
    setPhase("uploading");
    telemetry.push("recorder_stopped");
    try {
      await recorder.finish();
      const next = await roomApi.state(token);
      setState(next);
      setPhase("review");
    } catch (caught) {
      fail(caught, "Не удалось загрузить запись. Проверьте соединение и попробуйте снова.");
    }
  };

  const retake = () => {
    if (!question) return;
    void startRecording(question);
  };

  const goNext = async () => {
    clearDraftTimer();
    try {
      const next = await roomApi.next(token);
      if (question?.kind === "code") clearDraft(draftStorageKey(token, question.id));
      setState(next);
      setQuestion(null);
      setAudioUrl(null);
      setAvatar(null);
      if (next.status === "completed") {
        setPhase("done");
        await telemetry.flush();
        onFinished();
      } else {
        setPhase("intro");
        setResumed(false);
      }
    } catch (caught) {
      fail(caught, "Не удалось перейти к следующему вопросу");
    }
  };

  // ------------------------------------------------------------ секция кода

  const mergeAnswer = useCallback((answer: RoomAnswer, { draft = false }: { draft?: boolean } = {}) => {
    setState((current) => {
      if (!current) return current;
      const existing = current.answers.find((a) => a.id === answer.id);
      // Ответ на черновик, пришедший после отправки, не должен «разотправить» код.
      if (draft && existing?.code_submission?.submitted_at) return current;
      return {
        ...current,
        answers: existing ? current.answers.map((a) => (a.id === answer.id ? answer : a)) : [...current.answers, answer],
      };
    });
  }, []);

  const codeAnswer = state && question ? latestCodeAnswer(state, question.index) : null;
  const codeSubmission = codeAnswer?.code_submission ?? null;

  const scheduleDraftSave = (draft: CodeDraft) => {
    // После отправки правки уходят только явной повторной отправкой.
    if (!question || codeSubmission?.submitted_at) return;
    clearDraftTimer();
    draftTimerRef.current = window.setTimeout(() => {
      draftTimerRef.current = null;
      roomApi
        .saveCode(token, question.id, { ...draft, submit: false })
        .then((answer) => mergeAnswer(answer, { draft: true }))
        .catch(() => undefined); // черновик есть в localStorage — повторим со следующей правкой
    }, DRAFT_SAVE_DELAY_MS);
  };

  const submitCode = async (draft: CodeDraft) => {
    if (!question) return;
    clearDraftTimer();
    setCodeBusy("submit");
    setCodeError(null);
    try {
      mergeAnswer(await roomApi.saveCode(token, question.id, { ...draft, submit: true }));
    } catch (caught) {
      setCodeError(caught instanceof ApiError ? caught.message : "Не удалось отправить код. Проверьте соединение.");
    } finally {
      setCodeBusy(null);
    }
  };

  const runCode = async (draft: CodeDraft) => {
    if (!question) return;
    clearDraftTimer();
    setCodeBusy("run");
    setCodeError(null);
    try {
      mergeAnswer(await roomApi.runCode(token, question.id, draft));
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "runner_disabled") {
        setCodeError("Запуск кода появится позже — отправьте решение без запуска.");
      } else {
        setCodeError(caught instanceof ApiError ? caught.message : "Не удалось запустить код.");
      }
    } finally {
      setCodeBusy(null);
    }
  };

  const retakesLeft = useMemo(() => {
    if (!state || !question) return 0;
    const used = question.kind === "code" ? explanationAttempts(state, question.index) : attemptsUsed(state, question.index);
    return question.retakes_allowed + 1 - used;
  }, [state, question]);

  const currentQuestion = state?.questions.find((q) => q.index === index) ?? null;
  const uploadPercent = progress && progress.bytesTotal > 0 ? Math.round((progress.bytesUploaded / progress.bytesTotal) * 100) : 0;
  const remaining = question ? Math.max(0, question.max_answer_seconds - elapsed) : 0;
  const isCode = question?.kind === "code";
  const nextLabel = index + 1 < total ? "Следующий вопрос" : "Завершить интервью";

  if (phase === "loading") return <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />;

  if (phase === "error") {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          <p className="text-sm">{error}</p>
        </div>
        <Button onClick={() => window.location.reload()}>Обновить страницу</Button>
        <p className="text-xs text-muted-foreground">Записанные ответы сохранены — после обновления вы продолжите с текущего вопроса.</p>
      </div>
    );
  }

  if (phase === "done") {
    return (
      <div className="text-center">
        <h2 className="text-2xl font-bold">Спасибо, интервью завершено!</h2>
        <p className="mt-3 text-muted-foreground">
          Ответы переданы рекрутеру. Обычно ответ приходит в течение нескольких рабочих дней на e-mail.
        </p>
      </div>
    );
  }

  const stage = question ? (
    <AvatarStage question={question} avatar={avatar} audioRef={audioRef} hasAudio={Boolean(audioUrl)} onReplay={replayQuestion} />
  ) : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          Вопрос {index + 1} из {total}
        </span>
        <span>{phase === "recording" ? `Осталось ${formatSeconds(remaining)}` : ""}</span>
      </div>
      <Progress value={total ? ((index + (phase === "review" ? 1 : 0)) / total) * 100 : 0} className="h-1.5" />

      <div className={phase === "coding" ? "grid gap-4 md:grid-cols-[1fr_3fr]" : "grid gap-4 md:grid-cols-[2fr_3fr]"}>
        <div className="relative self-start overflow-hidden rounded-xl bg-black">
          <video ref={videoRef} muted playsInline autoPlay className="aspect-[4/3] w-full object-cover" />
          {phase === "recording" ? (
            <span className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">
              <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" /> Запись {formatSeconds(elapsed)}
            </span>
          ) : null}
        </div>

        <div className="flex min-w-0 flex-col justify-between rounded-xl border p-5">
          {phase === "intro" ? (
            <>
              <div>
                {resumed ? (
                  <p className="mb-3 rounded-md bg-muted p-3 text-sm">
                    С возвращением! Продолжим с вопроса {index + 1}.
                  </p>
                ) : null}
                <p className="text-lg font-semibold">Готовы к вопросу {index + 1}?</p>
                <p className="mt-2 text-sm text-muted-foreground">
                  {currentQuestion?.kind === "code"
                    ? "Это задача на код: после нажатия вопрос появится на экране и будет озвучен, ниже откроется редактор. Таймера нет — отправьте решение, когда будете готовы."
                    : "После нажатия вопрос появится на экране и будет озвучен. У вас будет время подготовиться, затем начнётся запись."}
                </p>
              </div>
              <Button size="lg" className="mt-6 w-full" onClick={showQuestion}>
                Показать вопрос
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </>
          ) : null}

          {phase === "coding" && question && state ? (
            <div className="space-y-4">
              {stage}
              <CodeEditor
                key={question.id}
                storageKey={draftStorageKey(token, question.id)}
                languages={state.code_runner.languages}
                maxBytes={state.code_runner.max_source_bytes}
                runnerEnabled={state.code_runner.enabled}
                initial={codeSubmission ? { language: codeSubmission.language, source: codeSubmission.source } : null}
                submittedAt={codeSubmission?.submitted_at ?? null}
                runResult={codeSubmission?.run_result ?? null}
                busy={codeBusy}
                error={codeError}
                onSubmit={submitCode}
                onRun={runCode}
                onChange={scheduleDraftSave}
              />
              {codeSubmission?.submitted_at ? (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-2">
                    <Button size="lg" className="flex-1" onClick={goNext}>
                      {nextLabel}
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                    {retakesLeft > 0 ? (
                      <Button size="lg" variant="outline" onClick={() => startRecording(question)}>
                        <Video className="mr-2 h-4 w-4" /> Записать пояснение
                      </Button>
                    ) : null}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Пояснение на камеру необязательно: расскажите, как рассуждали, — так оценят подход, а не только результат.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Отправьте код, чтобы перейти к следующему вопросу.</p>
              )}
            </div>
          ) : null}

          {(phase === "prep" || phase === "recording" || phase === "uploading" || phase === "review") && question ? (
            <div className="space-y-4">
              {stage}

              {phase === "prep" ? (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    Подготовка: запись начнётся через <span className="font-semibold text-foreground">{countdown} с</span>. Можно начать раньше.
                  </p>
                  <Button size="lg" className="w-full" onClick={() => startRecording(question)}>
                    <Mic className="mr-2 h-4 w-4" /> Начать ответ
                  </Button>
                </div>
              ) : null}

              {phase === "recording" ? (
                <div className="space-y-3">
                  {remaining <= 10 ? (
                    <p className="text-sm text-warning">Осталось {remaining} с — завершайте мысль.</p>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {isCode ? "Расскажите, как устроено ваше решение." : "Говорите свободно."} Ответ не дольше {formatSeconds(question.max_answer_seconds)}.
                    </p>
                  )}
                  <Button size="lg" variant="destructive" className="w-full" onClick={stopRecording}>
                    <Square className="mr-2 h-4 w-4" /> Завершить ответ
                  </Button>
                </div>
              ) : null}

              {phase === "uploading" ? (
                <div className="space-y-2">
                  <p className="flex items-center gap-2 text-sm">
                    <Loader2 className="h-4 w-4 animate-spin" /> Сохраняем запись…
                  </p>
                  <Progress value={uploadPercent} className="h-1.5" />
                </div>
              ) : null}

              {phase === "review" ? (
                <div className="space-y-3">
                  <p className="text-sm text-success">{isCode ? "Пояснение записано." : "Ответ сохранён."}</p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="lg" className="flex-1" onClick={goNext}>
                      {nextLabel}
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                    {retakesLeft > 0 ? (
                      <Button size="lg" variant="outline" onClick={retake}>
                        <RotateCcw className="mr-2 h-4 w-4" /> {isCode ? "Перезаписать пояснение" : "Перезаписать"} (осталось {retakesLeft})
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {isCode && codeSubmission ? <CodeSubmission submission={codeSubmission} className="border-t pt-4" /> : null}
            </div>
          ) : null}
        </div>
      </div>
      <audio ref={audioRef} preload="auto" className="hidden" />
      {state && currentQuestion && phase === "intro" && isAnswered(state, currentQuestion) ? (
        <p className="text-xs text-muted-foreground">
          {currentQuestion.kind === "code"
            ? "Код на этот вопрос уже отправлен — можно перейти дальше после показа вопроса."
            : "На этот вопрос уже есть записанный ответ — можно перейти дальше после показа вопроса."}
        </p>
      ) : null}
    </div>
  );
}
