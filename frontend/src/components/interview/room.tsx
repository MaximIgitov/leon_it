"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Loader2, Mic, RotateCcw, Square, Volume2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useInterviewTelemetry } from "@/hooks/use-interview-telemetry";
import { ApiError, API_BASE_URL } from "@/lib/api/client";
import { roomApi, type InterviewState, type SnapshotQuestion } from "@/lib/api/room";
import { AnswerRecorder, type UploadProgress } from "@/lib/media/recorder";
import type { DeviceCheckResult } from "@/components/interview/device-check";

type Phase = "loading" | "intro" | "prep" | "recording" | "uploading" | "review" | "done" | "error";

function formatSeconds(total: number): string {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function attemptsUsed(state: InterviewState, index: number): number {
  return state.answers.filter((a) => a.question_index === index && a.status !== "abandoned").length;
}

function hasUploaded(state: InterviewState, index: number): boolean {
  return state.answers.some((a) => a.question_index === index && a.status !== "recording" && a.status !== "abandoned");
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
  const [countdown, setCountdown] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resumed, setResumed] = useState(false);
  const recorderRef = useRef<AnswerRecorder | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<number | null>(null);
  const wakeLock = useRef<{ release: () => Promise<void> } | null>(null);

  const index = state?.current_question_index ?? 0;
  const total = state?.total_questions ?? 0;
  const getContext = useCallback(
    () => ({ questionIndex: index, answerId: recorderRef.current?.id ?? undefined }),
    [index],
  );
  const telemetry = useInterviewTelemetry(token, getContext, phase !== "loading" && phase !== "done");

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

  /** Показать вопрос: озвучка и отсчёт подготовки стартуют в одном клике (iOS). */
  const showQuestion = async () => {
    if (!state) return;
    try {
      const revealed = await roomApi.reveal(token, index);
      setQuestion(revealed.question);
      const url = revealed.audio_url ? `${API_BASE_URL.replace(/\/api$/, "")}${revealed.audio_url}` : null;
      setAudioUrl(url);
      setPhase("prep");
      setCountdown(revealed.question.prep_seconds);
      if (url && audioRef.current) {
        audioRef.current.src = url;
        void audioRef.current.play().catch(() => undefined);
      }
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
    try {
      const next = await roomApi.next(token);
      setState(next);
      setQuestion(null);
      setAudioUrl(null);
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

  const retakesLeft = useMemo(() => {
    if (!state || !question) return 0;
    return question.retakes_allowed + 1 - attemptsUsed(state, question.index);
  }, [state, question]);

  const uploadPercent = progress && progress.bytesTotal > 0 ? Math.round((progress.bytesUploaded / progress.bytesTotal) * 100) : 0;
  const remaining = question ? Math.max(0, question.max_answer_seconds - elapsed) : 0;

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          Вопрос {index + 1} из {total}
        </span>
        <span>{phase === "recording" ? `Осталось ${formatSeconds(remaining)}` : ""}</span>
      </div>
      <Progress value={total ? ((index + (phase === "review" ? 1 : 0)) / total) * 100 : 0} className="h-1.5" />

      <div className="grid gap-4 md:grid-cols-[2fr_3fr]">
        <div className="relative overflow-hidden rounded-xl bg-black">
          <video ref={videoRef} muted playsInline autoPlay className="aspect-[4/3] w-full object-cover" />
          {phase === "recording" ? (
            <span className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">
              <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" /> Запись {formatSeconds(elapsed)}
            </span>
          ) : null}
        </div>

        <div className="flex flex-col justify-between rounded-xl border p-5">
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
                  После нажатия вопрос появится на экране и будет озвучен. У вас будет время подготовиться, затем начнётся запись.
                </p>
              </div>
              <Button size="lg" className="mt-6 w-full" onClick={showQuestion}>
                Показать вопрос
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </>
          ) : null}

          {(phase === "prep" || phase === "recording" || phase === "uploading" || phase === "review") && question ? (
            <div className="space-y-4">
              <div className="flex items-start gap-2">
                <p className="text-lg font-semibold leading-snug">{question.text}</p>
                {audioUrl ? (
                  <button
                    type="button"
                    aria-label="Прослушать вопрос ещё раз"
                    className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-muted"
                    onClick={() => audioRef.current && void audioRef.current.play().catch(() => undefined)}
                  >
                    <Volume2 className="h-4 w-4" />
                  </button>
                ) : null}
              </div>

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
                    <p className="text-sm text-muted-foreground">Говорите свободно. Ответ не дольше {formatSeconds(question.max_answer_seconds)}.</p>
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
                  <p className="text-sm text-success">Ответ сохранён.</p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="lg" className="flex-1" onClick={goNext}>
                      {index + 1 < total ? "Следующий вопрос" : "Завершить интервью"}
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                    {retakesLeft > 0 ? (
                      <Button size="lg" variant="outline" onClick={retake}>
                        <RotateCcw className="mr-2 h-4 w-4" /> Перезаписать (осталось {retakesLeft})
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <audio ref={audioRef} preload="auto" className="hidden" />
      {hasUploaded(state ?? { answers: [] } as unknown as InterviewState, index) && phase === "intro" ? (
        <p className="text-xs text-muted-foreground">На этот вопрос уже есть записанный ответ — можно перейти дальше после показа вопроса.</p>
      ) : null}
    </div>
  );
}
