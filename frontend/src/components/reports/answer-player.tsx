"use client";

import { forwardRef, useImperativeHandle, useRef, useState } from "react";

import { API_BASE_URL } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export type AnswerPlayerHandle = {
  seek: (seconds: number) => void;
};

const SPEEDS = [1, 1.25, 1.5, 2];

export function absoluteMediaUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${API_BASE_URL.replace(/\/api$/, "")}${path}`;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export const AnswerPlayer = forwardRef<
  AnswerPlayerHandle,
  {
    src: string | null;
    contentType?: string | null;
    segments?: { start_s: number; end_s: number; text: string }[] | null;
    transcript?: string | null;
    className?: string;
  }
>(function AnswerPlayer({ src, contentType, segments, transcript, className }, ref) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [speed, setSpeed] = useState(1);
  const [current, setCurrent] = useState(0);

  useImperativeHandle(ref, () => ({
    seek: (seconds: number) => {
      const video = videoRef.current;
      if (!video) return;
      video.currentTime = Math.max(0, seconds);
      void video.play().catch(() => undefined);
      video.scrollIntoView({ behavior: "smooth", block: "center" });
    },
  }));

  const applySpeed = (value: number) => {
    setSpeed(value);
    if (videoRef.current) videoRef.current.playbackRate = value;
  };

  return (
    <div className={cn("space-y-3", className)}>
      {src ? (
        <video
          ref={videoRef}
          src={absoluteMediaUrl(src) ?? undefined}
          controls
          playsInline
          preload="metadata"
          className="w-full rounded-lg bg-black"
          onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => {
            e.currentTarget.playbackRate = speed;
          }}
        >
          {contentType ? <source src={absoluteMediaUrl(src) ?? undefined} type={contentType} /> : null}
        </video>
      ) : (
        <div className="flex aspect-video items-center justify-center rounded-lg bg-muted text-sm text-muted-foreground">
          Видео недоступно
        </div>
      )}
      <div className="flex items-center gap-1 text-xs">
        <span className="mr-1 text-muted-foreground">Скорость</span>
        {SPEEDS.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => applySpeed(value)}
            className={cn(
              "rounded-md px-2 py-1",
              speed === value ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/70",
            )}
          >
            {value}×
          </button>
        ))}
      </div>
      {segments && segments.length > 0 ? (
        <p className="thin-scrollbar max-h-56 overflow-y-auto rounded-lg border p-3 text-sm leading-relaxed">
          {segments.map((segment, index) => {
            const active = current >= segment.start_s && current < segment.end_s;
            return (
              <button
                key={`${segment.start_s}-${index}`}
                type="button"
                title={formatTime(segment.start_s)}
                onClick={() => {
                  if (videoRef.current) {
                    videoRef.current.currentTime = segment.start_s;
                    void videoRef.current.play().catch(() => undefined);
                  }
                }}
                className={cn(
                  "mr-1 rounded px-0.5 text-left hover:bg-accent",
                  active && "bg-accent text-accent-foreground",
                )}
              >
                {segment.text}
              </button>
            );
          })}
        </p>
      ) : transcript ? (
        <p className="thin-scrollbar max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg border p-3 text-sm leading-relaxed">
          {transcript}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">Транскрипт ещё готовится.</p>
      )}
    </div>
  );
});
