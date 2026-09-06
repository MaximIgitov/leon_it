"use client";

import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { FileText, VideoOff } from "lucide-react";
import { API_BASE_URL } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export type AnswerPlayerHandle = { seek: (seconds: number) => void };
const SPEEDS = [1, 1.25, 1.5, 2];
export function absoluteMediaUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${API_BASE_URL.replace(/\/api$/, "")}${path}`;
}
function formatTime(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

export const AnswerPlayer = forwardRef<AnswerPlayerHandle, {
  src: string | null;
  contentType?: string | null;
  segments?: { start_s: number; end_s: number; text: string }[] | null;
  transcript?: string | null;
  className?: string;
}>(function AnswerPlayer({ src, contentType, segments, transcript, className }, ref) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingSeek = useRef<number | null>(null);
  const [speed, setSpeed] = useState(1);
  const [current, setCurrent] = useState(0);
  const [mediaError, setMediaError] = useState(false);
  const playAt = (seconds: number) => {
    const video = videoRef.current;
    setCurrent(seconds);
    if (!video) return;
    if (video.readyState < 1) { pendingSeek.current = seconds; return; }
    video.currentTime = Math.max(0, Math.min(seconds, Number.isFinite(video.duration) ? video.duration : seconds));
    void video.play().catch(() => undefined);
  };
  useImperativeHandle(ref, () => ({ seek: (seconds) => {
    playAt(Math.max(0, seconds));
    videoRef.current?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "nearest" });
  } }));

  return <div className={cn("answer-player", className)}>
    <div className="answer-media">
      {src && !mediaError ? <video ref={videoRef} src={absoluteMediaUrl(src) ?? undefined} controls playsInline preload="metadata" aria-label="Видеозапись ответа" onError={() => setMediaError(true)} onTimeUpdate={event => setCurrent(event.currentTarget.currentTime)} onLoadedMetadata={event => {
        event.currentTarget.playbackRate = speed;
        if (pendingSeek.current !== null) { const seconds = pendingSeek.current; pendingSeek.current = null; playAt(seconds); }
      }}>{contentType && <source src={absoluteMediaUrl(src) ?? undefined} type={contentType} />}</video> : <div className="answer-media-empty"><VideoOff size={30} aria-hidden /><strong>{mediaError ? "Не удалось загрузить видео" : "Видео недоступно"}</strong><span>{transcript ? "Текст ответа доступен рядом" : "Запись появится после загрузки"}</span></div>}
      {src && !mediaError && <div className="answer-speed"><span>Скорость</span>{SPEEDS.map(value => <button key={value} type="button" aria-pressed={speed === value} onClick={() => { setSpeed(value); if (videoRef.current) videoRef.current.playbackRate = value; }}>{value}×</button>)}</div>}
    </div>
    <section className="answer-transcript" aria-label="Расшифровка ответа"><h3><FileText size={18} aria-hidden />Расшифровка</h3><div className="answer-transcript-scroll">
      {segments?.length ? segments.map((segment, index) => <button key={`${segment.start_s}-${index}`} type="button" className="transcript-segment" data-active={current >= segment.start_s && current < segment.end_s} onClick={() => playAt(segment.start_s)} aria-label={`${formatTime(segment.start_s)}. ${segment.text}`}><time>{formatTime(segment.start_s)}</time><span>{segment.text}</span></button>) : transcript ? <p className="answer-transcript-text">{transcript}</p> : <p className="answer-transcript-pending">Расшифровка появится после обработки ответа.</p>}
    </div></section>
  </div>;
});
