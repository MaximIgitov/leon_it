"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Mic, Square } from "lucide-react";

import { Mascot } from "@/components/brand/mascot";
import { MicBars, SpeechBars } from "@/components/interview/avatar-stage";
import { Button } from "@/components/ui/button";
import { pickMimeType } from "@/lib/media/recorder";
import { useVoiceActivity, type SilenceEvent } from "@/lib/media/voice-activity";
import { cn } from "@/lib/utils";

/*
 * Тренировочный вопрос повторяет комнату интервью один в один: та же сцена с
 * Леоном, камера кандидата в углу, статус «задаёт вопрос → слушает», в живом
 * диалоге пауза завершает ответ сама. Отличие одно — ничего не отправляется:
 * запись остаётся в браузере, и кандидат сразу смотрит, как выглядит его ответ.
 */

const PRACTICE_QUESTION = "Расскажите в двух предложениях, чем вы занимались на последнем месте работы.";
const MAX_SECONDS = 30;
const READ_QUESTION_MS = 3000;

export type PracticeMode = "live" | "push_to_talk";

export function formatClock(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

type State = "intro" | "asking" | "recording" | "playback";

export function PracticeQuestion({
  stream,
  onDone,
  mode = "live",
  doneLabel = "Перейти к интервью",
}: {
  stream: MediaStream;
  onDone: () => void;
  mode?: PracticeMode;
  doneLabel?: string;
}) {
  const [state, setState] = useState<State>("intro");
  const [url, setUrl] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number | null>(null);
  const askTimerRef = useRef<number | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const live = mode === "live";

  useEffect(() => {
    const video = videoRef.current;
    if (video && state !== "playback") {
      video.srcObject = stream;
      void video.play().catch(() => undefined);
    }
  }, [stream, state]);

  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
      if (timerRef.current) window.clearInterval(timerRef.current);
      if (askTimerRef.current) window.clearTimeout(askTimerRef.current);
    },
    [url],
  );

  useEffect(() => () => {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") { recorder.onstop = null; recorder.stop(); }
  }, []);

  const stop = () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  };

  const startRecording = () => {
    if (askTimerRef.current) window.clearTimeout(askTimerRef.current);
    if (recorderRef.current?.state === "recording") return;
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = () => {
      setUrl(URL.createObjectURL(new Blob(chunks, { type: recorder.mimeType })));
      setState("playback");
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
    recorderRef.current = recorder;
    recorder.start();
    setState("recording");
    setNote(null);
    setSeconds(0);
    timerRef.current = window.setInterval(() => {
      setSeconds((value) => {
        if (value + 1 >= MAX_SECONDS && recorder.state === "recording") recorder.stop();
        return value + 1;
      });
    }, 1000);
  };

  const ask = () => {
    setState("asking");
    setNote(null);
    if (live) {
      // Как в настоящем интервью: вопрос «прозвучал» — и мы слушаем.
      askTimerRef.current = window.setTimeout(startRecording, READ_QUESTION_MS);
    }
  };

  const onVoiceEvent = (event: SilenceEvent) => {
    if (event === "end_of_speech") stop();
    if (event === "no_speech") setNote("Не слышно речи. Скажите пару слов или нажмите «Завершить ответ».");
  };
  const voice = useVoiceActivity(stream, live && state === "recording", onVoiceEvent);

  const again = () => {
    if (url) URL.revokeObjectURL(url);
    setUrl(null);
    setSeconds(0);
    setState("intro");
  };

  const waitingPause = state === "recording" && live && voice.countdown !== null;
  const stageLabel =
    state === "intro"
      ? "готов"
      : state === "asking"
        ? "задаёт вопрос"
        : state === "recording"
          ? waitingPause
            ? "ждёт паузу"
            : "слушает"
          : "";
  const stageText =
    state === "intro"
      ? live
        ? "Леон задаст один пробный вопрос. Отвечайте как в разговоре: пауза в несколько секунд завершит ответ."
        : "Леон задаст один пробный вопрос. Вы нажмёте «Начать ответ», ответите и завершите кнопкой — как в интервью."
      : PRACTICE_QUESTION;

  return (
    <div className="space-y-4">
      <div className="practice-question-heading"><Mascot name="listen" /><div>
        <h2>Можно просто быть собой</h2>
        <p>Пробный вопрос · всё как в интервью, но запись останется только в твоём браузере</p>
      </div></div>

      {state === "playback" && url ? (
        <div className="relative overflow-hidden rounded-xl bg-black">
          <video src={url} controls playsInline className="aspect-video w-full" />
          <div className="absolute left-3 top-3 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white">
            Ваша запись · {formatClock(seconds)}
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card" data-testid="practice-stage">
          <div className="relative aspect-[4/3] w-full sm:aspect-[16/10]">
            <div className="interview-stage-art" data-speaking={state === "asking"}>
              <Mascot cutout name={state === "recording" ? "listen" : "leo"} eager />
            </div>
            <div className="absolute left-3 top-3 interview-stage-status">
              <span className="font-extrabold">Леон · ИИ-интервьюер</span>
              {stageLabel ? (
                <span className="normal-case tracking-normal opacity-90" aria-live="polite">
                  · {stageLabel}
                </span>
              ) : null}
              {state === "asking" ? <SpeechBars /> : null}
              {state === "recording" && !waitingPause ? <MicBars level={voice.level} /> : null}
            </div>
            {state === "recording" ? (
              <div className="absolute right-3 top-3">
                <span className="flex items-center gap-1.5 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
                  Запись {formatClock(seconds)} из {formatClock(MAX_SECONDS)}
                </span>
              </div>
            ) : null}
            {waitingPause ? (
              <div
                className="absolute bottom-3 left-1/2 max-w-[90%] -translate-x-1/2 rounded-full bg-black/70 px-4 py-1.5 text-center text-sm text-white"
                aria-live="polite"
              >
                Завершаю ответ через {voice.countdown} с. Продолжайте, если не закончили.
              </div>
            ) : null}
            <div className="absolute bottom-3 right-3 w-28 overflow-hidden rounded-lg shadow-lg ring-2 ring-white/80 sm:w-40">
              <video ref={videoRef} muted playsInline autoPlay className="aspect-[4/3] w-full bg-black object-cover" />
            </div>
          </div>
          <div className="flex items-start gap-2 border-t px-4 py-3">
            <p className={cn("min-w-0 flex-1 leading-snug", state === "intro" ? "text-sm text-muted-foreground" : "text-base font-semibold sm:text-lg")}>
              {stageText}
            </p>
          </div>
        </div>
      )}

      {note ? <p className="text-sm text-warning">{note}</p> : null}
      {state === "recording" && live && !note ? (
        <p className="text-sm text-muted-foreground">
          {waitingPause
            ? "Пауза. Если вы закончили, ответ завершится сам."
            : "Слушаю. Говорите свободно: пауза в несколько секунд завершит ответ."}
        </p>
      ) : null}
      {state === "playback" ? (
        <p className="text-sm text-muted-foreground">
          Вот твой ответ. Можно посмотреть запись или попробовать ещё раз.
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {state === "intro" ? (
          <Button size="lg" onClick={ask}>
            <Mic className="mr-2 h-4 w-4" /> Начать тренировку
          </Button>
        ) : null}
        {state === "asking" ? (
          <Button size="lg" onClick={startRecording}>
            <Mic className="mr-2 h-4 w-4" /> {live ? "Ответить сейчас" : "Начать ответ"}
          </Button>
        ) : null}
        {state === "recording" ? (
          <Button size="lg" variant="destructive" onClick={stop}>
            <Square className="mr-2 h-4 w-4" /> Завершить ответ
          </Button>
        ) : null}
        {state === "playback" ? (
          <>
            <Button size="lg" onClick={onDone}>
              {doneLabel} <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
            <Button size="lg" variant="outline" onClick={again}>
              Ещё раз
            </Button>
          </>
        ) : null}
        {state !== "playback" ? (
          <Button size="lg" variant="ghost" onClick={onDone}>
            Пропустить
          </Button>
        ) : null}
      </div>
    </div>
  );
}
