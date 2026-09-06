"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Mic, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { pickMimeType } from "@/lib/media/recorder";
import { useVoiceActivity, type SilenceEvent } from "@/lib/media/voice-activity";

/*
 * Тренировочный вопрос повторяет настоящий ход интервью, только ничего не
 * отправляет: вопрос показывается, идёт запись с таймером, в живом диалоге пауза
 * завершает ответ сама, затем кандидат смотрит свою запись. Так он понимает, как
 * выглядит ответ, до первого вопроса, который уже уйдёт рекрутеру.
 */

const PRACTICE_QUESTION = "Расскажите в двух предложениях, чем вы занимались на последнем месте работы.";
const MAX_SECONDS = 30;
const READ_QUESTION_MS = 2500;

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
}: {
  stream: MediaStream;
  onDone: () => void;
  mode?: PracticeMode;
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

  const statusChip =
    state === "asking" ? (
      <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
        ИИ-интервьюер · задаёт вопрос
      </span>
    ) : state === "recording" ? (
      <span className="flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white">
        <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
        Идёт запись · {formatClock(seconds)} из {formatClock(MAX_SECONDS)}
      </span>
    ) : null;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Тренировочный вопрос</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Один вопрос, чтобы освоиться с форматом. Ответ остаётся в вашем браузере, рекрутер его не увидит.
          {live
            ? " В интервью вопрос звучит, вы отвечаете, а пауза в несколько секунд завершает ответ сама."
            : " В интервью вы нажимаете «Начать ответ», отвечаете и завершаете кнопкой."}
        </p>
      </div>

      <div className="rounded-xl border bg-muted/30 p-4">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">Вопрос</p>
        <p className="mt-1 text-lg font-semibold">{PRACTICE_QUESTION}</p>
      </div>

      <div className="relative overflow-hidden rounded-xl bg-black">
        {state === "playback" && url ? (
          <video src={url} controls playsInline className="aspect-video w-full" />
        ) : (
          <video ref={videoRef} muted playsInline autoPlay className="aspect-video w-full object-cover" />
        )}
        {statusChip ? <div className="absolute left-3 top-3">{statusChip}</div> : null}
        {state === "recording" && live && voice.countdown !== null ? (
          <div className="absolute bottom-3 left-3 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white">
            Пауза · ответ завершится через {voice.countdown} с
          </div>
        ) : null}
        {state === "playback" ? (
          <div className="absolute left-3 top-3 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white">
            Ваша запись · {formatClock(seconds)}
          </div>
        ) : null}
      </div>

      {note ? <p className="text-sm text-warning">{note}</p> : null}
      {state === "recording" && live && !note ? (
        <p className="text-sm text-muted-foreground">
          {voice.countdown !== null
            ? "Пауза. Если вы закончили, ответ завершится сам."
            : "Слушаю. Говорите свободно: пауза в несколько секунд завершит ответ."}
        </p>
      ) : null}
      {state === "playback" ? (
        <p className="text-sm text-muted-foreground">
          Так выглядит ваш ответ. Он никуда не отправлен: в интервью запись уйдёт рекрутеру, а после паузы прозвучит следующий вопрос.
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
              Перейти к интервью <ArrowRight className="ml-2 h-4 w-4" />
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
