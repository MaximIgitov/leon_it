"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { Volume2 } from "lucide-react";

import { LogoMark } from "@/components/brand/logo";
import type { AvatarInfo, SnapshotQuestion } from "@/lib/api/room";
import { cn } from "@/lib/utils";

/*
 * «Сцена интервьюера». Если бэкенд отдал клип аватара (фиче-флаг AVATAR_ENABLED
 * и настроенный провайдер) — показываем видео; иначе персону «ИИ-интервьюер
 * LeonIT» с индикатором речи, который следит за озвучкой вопроса (TTS): тот же
 * <audio>, что и раньше играет в комнате, просто теперь на него подписана сцена.
 */
export function AvatarStage({
  question,
  avatar,
  audioRef,
  hasAudio,
  onReplay,
  className,
}: {
  question: SnapshotQuestion;
  avatar: AvatarInfo | null;
  audioRef: RefObject<HTMLAudioElement>;
  hasAudio: boolean;
  onReplay: () => void;
  className?: string;
}) {
  const [speaking, setSpeaking] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const clip = avatar?.enabled && avatar.clip_url ? avatar.clip_url : null;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || clip) return;
    const on = () => setSpeaking(true);
    const off = () => setSpeaking(false);
    audio.addEventListener("play", on);
    audio.addEventListener("playing", on);
    audio.addEventListener("pause", off);
    audio.addEventListener("ended", off);
    setSpeaking(!audio.paused && !audio.ended);
    return () => {
      audio.removeEventListener("play", on);
      audio.removeEventListener("playing", on);
      audio.removeEventListener("pause", off);
      audio.removeEventListener("ended", off);
    };
  }, [audioRef, clip, question.id]);

  const replay = () => {
    if (clip && videoRef.current) {
      videoRef.current.currentTime = 0;
      void videoRef.current.play().catch(() => undefined);
      return;
    }
    onReplay();
  };

  return (
    <div className={cn("flex items-start gap-4", className)} data-testid="avatar-stage">
      {clip ? (
        <video
          ref={videoRef}
          src={clip}
          autoPlay
          playsInline
          onPlay={() => setSpeaking(true)}
          onPause={() => setSpeaking(false)}
          onEnded={() => setSpeaking(false)}
          className="aspect-square w-32 shrink-0 rounded-xl bg-black object-cover sm:w-40"
          aria-label="ИИ-интервьюер LeonIT задаёт вопрос"
        />
      ) : (
        <div className="relative shrink-0">
          {speaking ? (
            <span className="absolute inset-0 animate-pulse-ring rounded-full bg-primary/40" aria-hidden />
          ) : null}
          <div
            className={cn(
              "relative flex h-14 w-14 items-center justify-center overflow-hidden rounded-full bg-primary ring-4 transition-shadow",
              speaking ? "ring-primary/30" : "ring-primary/10",
            )}
          >
            <LogoMark size={56} />
          </div>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          ИИ-интервьюер LeonIT
          <span className={cn("flex h-3 items-end gap-0.5", !speaking && "invisible")} aria-hidden>
            <span className="h-2 w-1 animate-pulse rounded-full bg-primary" />
            <span className="h-3 w-1 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
            <span className="h-1.5 w-1 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
          </span>
          {speaking ? (
            <span className="normal-case tracking-normal text-primary" aria-live="polite">
              говорит
            </span>
          ) : null}
        </p>
        <div className="mt-1 flex items-start gap-2">
          <p className="text-lg font-semibold leading-snug">{question.text}</p>
          {hasAudio || clip ? (
            <button
              type="button"
              aria-label="Прослушать вопрос ещё раз"
              className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-muted"
              onClick={replay}
            >
              <Volume2 className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
