"use client";

import { RowsSkeleton, Skeleton } from "@/components/ui/skeleton";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Mic, RotateCcw, Square, Video } from "lucide-react";

import { Mascot } from "@/components/brand/mascot";
import { toast } from "@/hooks/use-toast";
import { AvatarStage, type StageStatus } from "@/components/interview/avatar-stage";
import { CodeEditor, clearDraft, draftStorageKey, type CodeDraft } from "@/components/interview/code-editor";
import { CodeSubmission } from "@/components/reports/code-submission";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useFaceWatch } from "@/hooks/use-face-watch";
import { useInterviewTelemetry } from "@/hooks/use-interview-telemetry";
import { ApiError, API_BASE_URL } from "@/lib/api/client";
import {
  roomApi,
  type AvatarInfo,
  type FollowupStatus,
  type InterviewState,
  type RoomAnswer,
  type SnapshotQuestion,
} from "@/lib/api/room";
import { AnswerRecorder, type UploadProgress } from "@/lib/media/recorder";
import { useVoiceActivity, type SilenceEvent } from "@/lib/media/voice-activity";
import type { DeviceCheckResult } from "@/components/interview/device-check";

/*
 * Два формата интервью (настройка вакансии `interview_mode`).
 *
 * «Живой диалог» (по умолчанию): интервьюер задаёт вопрос голосом или клипом
 * аватара, после чего комната сразу слушает; пауза после ответа завершает
 * запись, ответ сохраняется, звучит следующий вопрос. Кнопки — только
 * страховка: «Ответить сейчас», если не хочется дослушивать, и «Завершить ответ».
 *
 * «Кнопка ответа» (push-to-talk): классический сценарий с подготовкой,
 * «Начать ответ», «Завершить ответ», перезаписью и «Следующий вопрос».
 *
 * Задачи на код в обоих форматах идут через редактор без таймера.
 */

type Phase =
  | "loading"
  | "intro"
  | "speaking"
  | "prep"
  | "coding"
  | "recording"
  | "uploading"
  | "review"
  | "done"
  | "error";
type InterviewMode = "live" | "push_to_talk";

// Автосохранение черновика кода на сервер: не чаще, чем раз в пару секунд после паузы.
const DRAFT_SAVE_DELAY_MS = 2500;
// Живой диалог: пауза перед прослушиванием, если вопрос никто не озвучивает.
const READ_QUESTION_MS = 2500;
// Живой диалог: страховка, если событие «клип дозвучал» так и не пришло.
const SPEAK_BUDGET_MS = 90_000;

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

export function interviewModeOf(state: InterviewState | null): InterviewMode {
  return state?.settings.interview_mode === "push_to_talk" ? "push_to_talk" : "live";
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
  const [waitingFollowups, setWaitingFollowups] = useState(false);
  // Живой диалог: следующий вопрос задаётся сам, без экрана «Готовы к вопросу?».
  const [autoAdvance, setAutoAdvance] = useState(false);
  const [liveNote, setLiveNote] = useState<string | null>(null);
  const recorderRef = useRef<AnswerRecorder | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<number | null>(null);
  const draftTimerRef = useRef<number | null>(null);
  const speakTimerRef = useRef<number | null>(null);
  const spokenRef = useRef(false);
  const stoppingRef = useRef(false);
  // Вопрос, для которого запись уже стартует или идёт: второй старт (двойной
  // вызов из таймера в dev-режиме React, два события подряд) создал бы вторую
  // попытку на сервере и сломал бы загрузку.
  const startingRef = useRef<string | null>(null);
  const elapsedRef = useRef(0);
  const countdownRef = useRef(0);
  const spokenHandlerRef = useRef<() => void>(() => undefined);
  const wakeLock = useRef<{ release: () => Promise<void> } | null>(null);

  const index = state?.current_question_index ?? 0;
  const total = state?.total_questions ?? 0;
  const mode = interviewModeOf(state);
  const live = mode === "live";
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

  // Превью камеры на протяжении всей комнаты (элемент переезжает между раскладками).
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

  const clearSpeakTimer = () => {
    if (speakTimerRef.current) {
      window.clearTimeout(speakTimerRef.current);
      speakTimerRef.current = null;
    }
  };

  useEffect(
    () => () => {
      clearDraftTimer();
      clearSpeakTimer();
    },
    [],
  );

  const replayQuestion = () => {
    if (audioRef.current && audioUrl) void audioRef.current.play().catch(() => undefined);
  };

  const startRecording = async (current: SnapshotQuestion) => {
    if (startingRef.current === current.id) return;
    startingRef.current = current.id;
    clearTimer();
    clearSpeakTimer();
    audioRef.current?.pause();
    setProgress(null);
    setLiveNote(null);
    stoppingRef.current = false;
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
      elapsedRef.current = 0;
      setElapsed(0);
      timerRef.current = window.setInterval(() => {
        elapsedRef.current += 1;
        setElapsed(elapsedRef.current);
        if (elapsedRef.current >= current.max_answer_seconds) {
          clearTimer();
          void stopRecording();
        }
      }, 1000);
    } catch (caught) {
      startingRef.current = null;
      fail(caught, "Не удалось начать запись");
    }
  };

  /** Вопрос прозвучал (клип аватара, озвучка или пауза на чтение): живой диалог начинает слушать. */
  const onQuestionSpoken = (current: SnapshotQuestion) => {
    if (spokenRef.current) return;
    spokenRef.current = true;
    clearSpeakTimer();
    if (live) void startRecording(current);
  };
  spokenHandlerRef.current = () => {
    if (question && phase === "speaking") onQuestionSpoken(question);
  };

  // Озвучка TTS дозвучала — тот же сигнал, что и конец клипа аватара.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const handler = () => spokenHandlerRef.current();
    audio.addEventListener("ended", handler);
    return () => audio.removeEventListener("ended", handler);
  }, [phase]);

  /** Показать вопрос: озвучка и отсчёт стартуют в одном клике (iOS). */
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
      if (live) {
        spokenRef.current = false;
        setPhase("speaking");
        clearSpeakTimer();
        const speaks = avatarSpeaks || Boolean(url);
        const budget = speaks
          ? Math.min(SPEAK_BUDGET_MS, Math.max(15_000, ((revealed.avatar?.duration_s ?? 45) + 8) * 1000))
          : READ_QUESTION_MS;
        speakTimerRef.current = window.setTimeout(() => onQuestionSpoken(revealed.question), budget);
        return;
      }
      setPhase("prep");
      countdownRef.current = revealed.question.prep_seconds;
      setCountdown(revealed.question.prep_seconds);
      if (revealed.question.prep_seconds > 0) {
        clearTimer();
        timerRef.current = window.setInterval(() => {
          countdownRef.current = Math.max(0, countdownRef.current - 1);
          setCountdown(countdownRef.current);
          if (countdownRef.current <= 0) {
            clearTimer();
            void startRecording(revealed.question);
          }
        }, 1000);
      } else {
        void startRecording(revealed.question);
      }
    } catch (caught) {
      fail(caught, "Не удалось получить вопрос");
    }
  };

  // Живой диалог: после сохранения ответа следующий вопрос задаётся сам.
  useEffect(() => {
    if (live && autoAdvance && phase === "intro" && state) {
      setAutoAdvance(false);
      void showQuestion();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAdvance, phase, state, live]);

  /** Ожидание блока уточнений: показываем подпись и опрашиваем статус. */
  const waitForFollowups = async () => {
    let status: FollowupStatus;
    try {
      status = await roomApi.followups(token);
    } catch {
      return;
    }
    if (!status.enabled || status.ready) return;
    setWaitingFollowups(true);
    const deadline = Date.now() + status.wait_seconds * 1000;
    try {
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        try {
          const next = await roomApi.followups(token);
          if (next.ready) return;
        } catch {
          return;
        }
      }
    } finally {
      setWaitingFollowups(false);
    }
  };

  const goNext = async () => {
    clearDraftTimer();
    try {
      // Перед финалом ждём транскрипты для уточняющих вопросов — но не дольше
      // бюджета: держать кандидата у экрана из-за очереди нельзя.
      if (index + 1 >= total) await waitForFollowups();
      const next = await roomApi.next(token);
      if (question?.kind === "code") clearDraft(draftStorageKey(token, question.id));
      setState(next);
      setQuestion(null);
      setAudioUrl(null);
      setAvatar(null);
      if (next.status === "completed") {
        setPhase("done");
        toast({ title: "Интервью пройдено!", description: "Все ответы сохранены.", celebrate: true });
        await telemetry.flush();
        onFinished();
      } else {
        setPhase("intro");
        setResumed(false);
        if (live) setAutoAdvance(true);
      }
    } catch (caught) {
      fail(caught, "Не удалось перейти к следующему вопросу");
    }
  };

  const stopRecording = async () => {
    if (stoppingRef.current) return;
    stoppingRef.current = true;
    clearTimer();
    const recorder = recorderRef.current;
    if (!recorder) return;
    setPhase("uploading");
    telemetry.push("recorder_stopped");
    try {
      await recorder.finish();
      startingRef.current = null;
      const next = await roomApi.state(token);
      setState(next);
      if (live && question?.kind !== "code") {
        await goNext();
      } else {
        setPhase("review");
      }
    } catch (caught) {
      startingRef.current = null;
      fail(caught, "Не удалось загрузить запись. Проверьте соединение и попробуйте снова.");
    }
  };

  // Живой диалог: микрофон слушает детектор пауз.
  const onVoiceEvent = (event: SilenceEvent) => {
    if (event === "end_of_speech") {
      telemetry.push("live_end_of_speech", { elapsed_s: elapsedRef.current });
      void stopRecording();
    } else if (event === "no_speech") {
      telemetry.push("live_no_speech");
      setLiveNote("Не слышу вас. Говорите, когда будете готовы, или завершите ответ кнопкой.");
    } else if (event === "speech_started") {
      setLiveNote(null);
    }
  };
  const voice = useVoiceActivity(devices.stream, live && phase === "recording" && question?.kind !== "code", onVoiceEvent);

  /** Новая попытка на тот же вопрос: снимаем защиту от повторного старта явно. */
  const recordAgain = (current: SnapshotQuestion) => {
    startingRef.current = null;
    void startRecording(current);
  };

  const retake = () => {
    if (!question) return;
    recordAgain(question);
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
  const nextLabel = waitingFollowups
    ? "Готовим уточняющие вопросы…"
    : index + 1 < total
      ? "Следующий вопрос"
      : "Завершить интервью";

  if (phase === "loading") return <RowsSkeleton />;

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
      <div className="interview-finished">
        <Mascot name="celebrate" eager />
        <h2>Отлично, всё получилось!</h2>
        <p className="mt-3 text-muted-foreground">
          Ответы уже у команды найма. О следующих шагах напишут на e-mail.
        </p>
      </div>
    );
  }

  const stageStatus: StageStatus =
    phase === "speaking"
      ? "speaking"
      : phase === "recording"
        ? "listening"
        : phase === "uploading"
          ? "saving"
          : waitingFollowups || autoAdvance
            ? "thinking"
            : "idle";
  const stagePlaceholder = autoAdvance
    ? "Следующий вопрос…"
    : waitingFollowups
      ? "Интервьюер думает над уточнением…"
      : resumed
        ? `Продолжим с вопроса ${index + 1}`
        : live
          ? "Интервьюер готов начать"
          : "Интервьюер ждёт, когда вы будете готовы";
  const cameraPip = (
    <div className="absolute bottom-3 right-3 w-28 overflow-hidden rounded-lg shadow-lg ring-2 ring-white/80 sm:w-40">
      <video ref={videoRef} muted playsInline autoPlay className="aspect-[4/3] w-full bg-black object-cover" />
    </div>
  );
  const recordingBadge =
    phase === "recording" ? (
      <span className="flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">
        <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" /> Запись {formatSeconds(elapsed)}
      </span>
    ) : null;
  const introTitle = live
    ? index === 0 && !resumed
      ? "Начнём интервью?"
      : `Готовы к вопросу ${index + 1}?`
    : `Готовы к вопросу ${index + 1}?`;
  const introText =
    currentQuestion?.kind === "code"
      ? "Это задача на код: после нажатия вопрос появится на экране и будет озвучен, ниже откроется редактор. Таймера нет — отправьте решение, когда будете готовы."
      : live
        ? "Леон задаст вопрос. Отвечайте свободно: пауза в несколько секунд сохранит ответ. Завершить его можно и кнопкой."
        : "После нажатия вопрос появится на экране и будет озвучен. У вас будет время подготовиться, затем начнётся запись.";
  const introButton = live ? (index === 0 && !resumed ? "Начать интервью" : "Продолжить") : "Показать вопрос";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          Вопрос {index + 1} из {total}
        </span>
        <span>{phase === "recording" ? `Осталось ${formatSeconds(remaining)}` : ""}</span>
      </div>
      <Progress value={total ? ((index + (phase === "review" ? 1 : 0)) / total) * 100 : 0} className="h-1.5" />

      {phase === "coding" && question && state ? (
        <div className="grid gap-4 md:grid-cols-[1fr_3fr]">
          <div className="relative self-start overflow-hidden rounded-xl bg-black">
            <video ref={videoRef} muted playsInline autoPlay className="aspect-[4/3] w-full object-cover" />
          </div>
          <div className="flex min-w-0 flex-col rounded-xl border p-5">
            <div className="space-y-4">
              <AvatarStage variant="compact" question={question} avatar={avatar} audioRef={audioRef} hasAudio={Boolean(audioUrl)} onReplay={replayQuestion} />
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
                      <Button size="lg" variant="outline" onClick={() => recordAgain(question)}>
                        <Video className="mr-2 h-4 w-4" /> Записать пояснение
                      </Button>
                    ) : null}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    При желании запишите пояснение к решению.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Отправьте код, чтобы перейти к следующему вопросу.</p>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <AvatarStage
            question={question}
            avatar={avatar}
            poster={state?.avatar?.poster_url ?? null}
            audioRef={audioRef}
            hasAudio={Boolean(audioUrl)}
            onReplay={replayQuestion}
            onSpoken={() => spokenHandlerRef.current()}
            status={stageStatus}
            level={voice.level}
            countdown={live && phase === "recording" ? voice.countdown : null}
            badge={recordingBadge}
            placeholder={stagePlaceholder}
          >
            {cameraPip}
          </AvatarStage>

          {phase === "intro" && !autoAdvance ? (
            <div className="rounded-xl border p-5">
              {resumed ? (
                <p className="mb-3 rounded-md bg-secondary p-3 text-sm">
                  С возвращением! Продолжим с вопроса {index + 1}.
                </p>
              ) : null}
              <p className="text-lg font-semibold">{introTitle}</p>
              <p className="mt-2 text-sm text-muted-foreground">{introText}</p>
              <Button size="lg" className="mt-6 w-full" onClick={showQuestion}>
                {introButton}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
              {state && currentQuestion && isAnswered(state, currentQuestion) ? (
                <p className="mt-3 text-xs text-muted-foreground">
                  {currentQuestion.kind === "code"
                    ? "Код на этот вопрос уже отправлен — можно перейти дальше после показа вопроса."
                    : "На этот вопрос уже есть записанный ответ — можно перейти дальше после показа вопроса."}
                </p>
              ) : null}
            </div>
          ) : null}

          {phase === "speaking" && question ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4">
              <p className="text-sm text-muted-foreground">Интервьюер задаёт вопрос. Как дослушаете, начнём слушать вас.</p>
              <Button variant="outline" onClick={() => onQuestionSpoken(question)}>
                <Mic className="mr-2 h-4 w-4" /> Ответить сейчас
              </Button>
            </div>
          ) : null}

          {phase === "prep" && question ? (
            <div className="space-y-3 rounded-xl border p-4">
              <p className="text-sm text-muted-foreground">
                Подготовка: запись начнётся через <span className="font-semibold text-foreground">{countdown} с</span>. Можно начать раньше.
              </p>
              <Button size="lg" className="w-full" onClick={() => startRecording(question)}>
                <Mic className="mr-2 h-4 w-4" /> Начать ответ
              </Button>
            </div>
          ) : null}

          {phase === "recording" && question ? (
            <div className="space-y-3 rounded-xl border p-4">
              {remaining <= 10 ? (
                <p className="text-sm text-warning">Осталось {remaining} с — завершайте мысль.</p>
              ) : live ? (
                <p className={liveNote ? "text-sm text-warning" : "text-sm text-muted-foreground"}>
                  {liveNote ??
                    (voice.countdown !== null
                      ? "Пауза. Если вы закончили, ответ сохранится сам."
                      : "Слушаю. Говорите свободно: пауза в несколько секунд завершит ответ.")}{" "}
                  Ответ не дольше {formatSeconds(question.max_answer_seconds)}.
                </p>
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
            <div className="space-y-2 rounded-xl border p-4">
              <p className="flex items-center gap-2 text-sm">
                <Skeleton className="h-4 w-4 rounded-md" /> {waitingFollowups ? "Готовим уточняющие вопросы…" : "Сохраняем ответ…"}
              </p>
              <Progress value={uploadPercent} className="h-1.5" />
            </div>
          ) : null}

          {phase === "review" && question ? (
            <div className="space-y-3 rounded-xl border p-4">
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
              {isCode && codeSubmission ? <CodeSubmission submission={codeSubmission} className="border-t pt-4" /> : null}
            </div>
          ) : null}
        </div>
      )}
      <audio ref={audioRef} preload="auto" className="hidden" />
    </div>
  );
}
