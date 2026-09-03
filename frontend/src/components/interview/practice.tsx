"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Mic, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { pickMimeType } from "@/lib/media/recorder";

const PRACTICE_QUESTION = "Тренировочный вопрос: расскажите в двух предложениях, чем вы занимались на последнем месте работы.";

/** Тренировочный вопрос: запись остаётся в браузере и никуда не отправляется. */
export function PracticeQuestion({ stream, onDone }: { stream: MediaStream; onDone: () => void }) {
  const [state, setState] = useState<"idle" | "recording" | "playback">("idle");
  const [url, setUrl] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (video && state !== "playback") {
      video.srcObject = stream;
      void video.play().catch(() => undefined);
    }
  }, [stream, state]);

  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
    if (timerRef.current) window.clearInterval(timerRef.current);
  }, [url]);

  const start = () => {
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
    setSeconds(0);
    timerRef.current = window.setInterval(() => {
      setSeconds((value) => {
        if (value + 1 >= 30 && recorder.state === "recording") recorder.stop();
        return value + 1;
      });
    }, 1000);
  };

  const stop = () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Это тренировка: ответ никуда не отправляется. Так вы освоитесь с форматом до первого настоящего вопроса.
      </p>
      <p className="text-lg font-semibold">{PRACTICE_QUESTION}</p>
      {state === "playback" && url ? (
        <video src={url} controls playsInline className="aspect-video w-full rounded-xl bg-black" />
      ) : (
        <video ref={videoRef} muted playsInline autoPlay className="aspect-video w-full rounded-xl bg-black object-cover" />
      )}
      <div className="flex flex-wrap gap-2">
        {state === "idle" ? (
          <Button size="lg" onClick={start}>
            <Mic className="mr-2 h-4 w-4" /> Начать тренировочный ответ
          </Button>
        ) : null}
        {state === "recording" ? (
          <Button size="lg" variant="destructive" onClick={stop}>
            <Square className="mr-2 h-4 w-4" /> Завершить ({seconds} с)
          </Button>
        ) : null}
        {state === "playback" ? (
          <>
            <Button size="lg" onClick={onDone}>
              Перейти к интервью <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
            <Button size="lg" variant="outline" onClick={() => setState("idle")}>
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
