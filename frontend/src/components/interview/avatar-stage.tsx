"use client";

import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Volume2 } from "lucide-react";

import { Mascot } from "@/components/brand/mascot";
import type { AvatarInfo, SnapshotQuestion } from "@/lib/api/room";
import { cn } from "@/lib/utils";

/*
 * «Сцена интервьюера». Если бэкенд отдал клип аватара (фиче-флаг AVATAR_ENABLED,
 * настроенный провайдер и включённый аватар у вакансии) — показываем видео;
 * иначе персону «ИИ-интервьюер LeonIT» с индикатором речи, который следит за
 * озвучкой вопроса (TTS): тот же <audio>, что играет в комнате.
 *
 * Два варианта. «stage» — во весь экран диалога: аватар занимает центральную
 * форму, камера кандидата приходит детьми и живёт в углу, текст вопроса — под
 * видео. «compact» — узкая строка для задач на код, где место нужно редактору.
 */

export type StageStatus = "idle" | "speaking" | "listening" | "thinking" | "saving";

const STATUS_LABELS: Record<StageStatus, string> = {
  idle: "",
  speaking: "говорит",
  listening: "слушает",
  thinking: "думает",
  saving: "сохраняет ответ",
};

type Props = {
  variant?: "stage" | "compact";
  question: SnapshotQuestion | null;
  avatar: AvatarInfo | null;
  /** Кадр аватара, пока клипа вопроса ещё нет: видео первого вопроса на паузе. */
  poster?: string | null;
  audioRef: RefObject<HTMLAudioElement | null>;
  hasAudio: boolean;
  onReplay: () => void;
  /** Клип аватара дозвучал или не смог воспроизвестись: комната начинает слушать. */
  onSpoken?: () => void;
  status?: StageStatus;
  /** Уровень микрофона 0…1 — индикатор «слушает». */
  level?: number;
  /** Секунды до автозавершения ответа, пока идёт пауза. */
  countdown?: number | null;
  /** Правый верхний угол: индикатор записи с таймером. */
  badge?: ReactNode;
  /** Подпись, пока вопроса ещё нет. */
  placeholder?: string;
  /** Картинка-в-картинке: камера кандидата. */
  children?: ReactNode;
  className?: string;
};

function useAudioSpeaking(audioRef: RefObject<HTMLAudioElement | null>, enabled: boolean, key: string): boolean {
  const [speaking, setSpeaking] = useState(false);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !enabled) {
      setSpeaking(false);
      return;
    }
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
  }, [audioRef, enabled, key]);
  return speaking;
}

export function SpeechBars() {
  return (
    <span className="flex h-3 items-end gap-0.5" aria-hidden>
      <span className="h-2 w-1 animate-pulse rounded-full bg-primary" />
      <span className="h-3 w-1 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
      <span className="h-1.5 w-1 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
    </span>
  );
}

export function MicBars({ level }: { level: number }) {
  const height = (factor: number) => `${Math.max(3, Math.min(14, 3 + level * 80 * factor))}px`;
  return (
    <span className="flex h-3.5 items-end gap-0.5" aria-hidden data-testid="mic-level">
      <span className="w-1 rounded-full bg-emerald-400 transition-all" style={{ height: height(0.7) }} />
      <span className="w-1 rounded-full bg-emerald-400 transition-all" style={{ height: height(1) }} />
      <span className="w-1 rounded-full bg-emerald-400 transition-all" style={{ height: height(0.5) }} />
    </span>
  );
}

function ReplayButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Прослушать вопрос ещё раз"
      className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-secondary"
      onClick={onClick}
    >
      <Volume2 className="h-4 w-4" />
    </button>
  );
}

export function AvatarStage(props: Props) {
  if (props.variant === "compact") return <CompactStage {...props} />;
  return <FullStage {...props} />;
}

function FullStage({
  question,
  avatar,
  poster = null,
  audioRef,
  hasAudio,
  onReplay,
  onSpoken,
  status = "idle",
  level = 0,
  countdown = null,
  badge,
  placeholder = "Интервьюер готов",
  children,
  className,
}: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const clip = avatar?.enabled && avatar.clip_url ? avatar.clip_url : null;
  const [clipPlaying, setClipPlaying] = useState(false);
  const audioSpeaking = useAudioSpeaking(audioRef, !clip, question?.id ?? "");
  const speaking = clip ? clipPlaying : audioSpeaking || status === "speaking";
  const label = speaking ? STATUS_LABELS.speaking : STATUS_LABELS[status];

  const replay = () => {
    if (clip && videoRef.current) {
      videoRef.current.currentTime = 0;
      void videoRef.current.play().catch(() => undefined);
      return;
    }
    onReplay();
  };

  return (
    <div className={cn("overflow-hidden rounded-xl border bg-card", className)} data-testid="avatar-stage">
      <div className="relative aspect-[4/3] w-full bg-white sm:aspect-[16/10]">
        {clip ? (
          <video
            key={clip}
            ref={videoRef}
            src={clip}
            autoPlay
            playsInline
            onPlay={() => setClipPlaying(true)}
            onPause={() => setClipPlaying(false)}
            onEnded={() => {
              setClipPlaying(false);
              onSpoken?.();
            }}
            onError={() => {
              setClipPlaying(false);
              onSpoken?.();
            }}
            className="h-full w-full object-contain"
            aria-label="ИИ-интервьюер LeonIT задаёт вопрос"
          />
        ) : poster ? (
          <video
            key={poster}
            src={poster}
            muted
            playsInline
            preload="auto"
            className="h-full w-full object-contain"
            aria-label="ИИ-интервьюер LeonIT"
          />
        ) : (
          <div className="interview-stage-art" data-speaking={speaking}>
            <Mascot cutout name={status === "thinking" || status === "saving" ? "think" : status === "listening" ? "listen" : "leo"} eager />
          </div>
        )}

        <div className="absolute left-3 top-3 interview-stage-status">
          <span className="font-extrabold">Леон · ИИ-интервьюер</span>
          {label ? (
            <span className="normal-case tracking-normal opacity-90" aria-live="polite">
              · {label}
            </span>
          ) : null}
          {speaking ? <SpeechBars /> : null}
          {!speaking && status === "listening" ? <MicBars level={level} /> : null}
        </div>
        {badge ? <div className="absolute right-3 top-3">{badge}</div> : null}
        {countdown !== null && countdown !== undefined ? (
          <div
            className="absolute bottom-3 left-1/2 max-w-[90%] -translate-x-1/2 rounded-full bg-black/70 px-4 py-1.5 text-center text-sm text-white"
            aria-live="polite"
          >
            Завершаю ответ через {countdown} с. Продолжайте, если не закончили.
          </div>
        ) : null}
        {children}
      </div>
      <div className="flex items-start gap-2 border-t px-4 py-3">
        <p className={cn("min-w-0 flex-1 leading-snug", question ? "text-base font-semibold sm:text-lg" : "text-sm text-muted-foreground")}>
          {question ? question.text : placeholder}
        </p>
        {question && (hasAudio || clip) ? <ReplayButton onClick={replay} /> : null}
      </div>
    </div>
  );
}

function CompactStage({ question, avatar, audioRef, hasAudio, onReplay, className }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const clip = avatar?.enabled && avatar.clip_url ? avatar.clip_url : null;
  const [clipPlaying, setClipPlaying] = useState(false);
  const audioSpeaking = useAudioSpeaking(audioRef, !clip, question?.id ?? "");
  const speaking = clip ? clipPlaying : audioSpeaking;

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
          onPlay={() => setClipPlaying(true)}
          onPause={() => setClipPlaying(false)}
          onEnded={() => setClipPlaying(false)}
          className="aspect-square w-32 shrink-0 rounded-xl bg-black object-cover sm:w-40"
          aria-label="ИИ-интервьюер LeonIT задаёт вопрос"
        />
      ) : (
        <div className="relative shrink-0">
          {speaking ? <span className="absolute inset-0 animate-pulse-ring rounded-full bg-primary/40" aria-hidden /> : null}
          <div
            className={cn(
              "relative flex h-14 w-14 items-center justify-center overflow-hidden rounded-full bg-green-soft ring-4 transition-shadow",
              speaking ? "ring-primary/30" : "ring-primary/10",
            )}
          >
            <Mascot cutout name="leo" eager />
          </div>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          ИИ-интервьюер LeonIT
          {speaking ? <SpeechBars /> : null}
          {speaking ? (
            <span className="normal-case tracking-normal text-primary" aria-live="polite">
              говорит
            </span>
          ) : null}
        </p>
        <div className="mt-1 flex items-start gap-2">
          <p className="text-lg font-semibold leading-snug">{question?.text}</p>
          {hasAudio || clip ? <ReplayButton onClick={replay} /> : null}
        </div>
      </div>
    </div>
  );
}
