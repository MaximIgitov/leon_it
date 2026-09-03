import { Check, Square } from "lucide-react";

import { cn } from "@/lib/utils";

/*
 * Иллюстрации лендинга — лёгкие SVG и CSS, без растровых картинок.
 * Силуэт человека в кадре и макет комнаты интервью повторяют реальный
 * интерфейс (components/interview/room.tsx), чтобы кандидат узнал экран.
 */

export function PersonSilhouette({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 160 120"
      preserveAspectRatio="xMidYMid slice"
      className={cn("h-full w-full", className)}
      aria-hidden="true"
      focusable="false"
    >
      <rect width="160" height="120" fill="#12121c" />
      <rect width="160" height="120" fill="url(#leonit-silhouette-light)" />
      <defs>
        <radialGradient id="leonit-silhouette-light" cx="0.5" cy="0.25" r="0.75">
          <stop offset="0" stopColor="#2b2b45" />
          <stop offset="1" stopColor="#0c0c15" />
        </radialGradient>
      </defs>
      <circle cx="80" cy="48" r="21" fill="#3f3f5e" />
      <path d="M34 122c3-30 22-44 46-44s43 14 46 44z" fill="#3f3f5e" />
    </svg>
  );
}

/** Макет экрана комнаты: вопрос, таймер, превью камеры и кнопка завершения. */
export function RoomPreview({ className }: { className?: string }) {
  return (
    <div
      role="img"
      aria-label="Пример экрана комнаты интервью: вопрос 2 из 5, идёт запись ответа, до конца ответа 1:42"
      className={cn("relative", className)}
    >
      <div aria-hidden="true" className="rounded-2xl border bg-card p-4 shadow-xl shadow-primary/5 sm:p-5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Вопрос 2 из 5</span>
          <span>Осталось 1:42</span>
        </div>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div className="h-full w-2/5 rounded-full bg-primary" />
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-[2fr_3fr]">
          <div className="relative aspect-[4/3] overflow-hidden rounded-xl bg-black">
            <PersonSilhouette />
            <span className="absolute left-2 top-2 flex items-center gap-1.5 rounded-full bg-black/60 px-2 py-0.5 text-[11px] text-white">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
              Запись 1:18
            </span>
          </div>
          <div className="flex flex-col justify-between rounded-xl border p-3 sm:p-4">
            <div>
              <p className="text-sm font-semibold leading-snug">
                Расскажите о задаче, которой гордитесь. Что было самым сложным и как вы это решили?
              </p>
              <p className="mt-2 text-xs text-muted-foreground">Говорите свободно. Ответ не дольше 3:00.</p>
            </div>
            <div className="mt-3 flex h-9 items-center justify-center gap-2 rounded-md bg-destructive text-xs font-medium text-destructive-foreground">
              <Square className="h-3 w-3" />
              Завершить ответ
            </div>
          </div>
        </div>
      </div>
      <div
        aria-hidden="true"
        className="absolute -bottom-4 left-4 hidden items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-xs shadow-md sm:flex"
      >
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-success text-success-foreground">
          <Check className="h-3 w-3" />
        </span>
        Ответ 1 сохранён
      </div>
    </div>
  );
}

/** Тёмный кадр-постер для блока видеодемо: знак LeonIT и подпись. */
export function DemoFrame({
  caption,
  hint,
  className,
  testId,
}: {
  caption: string;
  hint?: string;
  className?: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className={cn(
        "relative flex aspect-video w-full flex-col items-center justify-center overflow-hidden rounded-2xl border border-white/10 bg-[#0f0f1a] text-white",
        className,
      )}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(70%_80%_at_50%_0%,rgba(20,10,240,0.35),transparent)]"
      />
      <svg viewBox="0 0 256 256" width="56" height="56" aria-hidden="true" focusable="false" className="relative">
        <rect width="256" height="256" rx="56" fill="#140AF0" />
        <path d="M66 50h34v122h90v34H66V50z" fill="#ffffff" />
      </svg>
      <p className="relative mt-4 px-6 text-center text-base font-semibold sm:text-lg">{caption}</p>
      {hint ? <p className="relative mt-1 px-6 text-center text-sm text-white/60">{hint}</p> : null}
    </div>
  );
}
