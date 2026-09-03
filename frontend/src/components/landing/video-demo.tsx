import fs from "node:fs";
import path from "node:path";

import { DemoFrame } from "@/components/landing/illustrations";
import { Section } from "@/components/landing/section";

/*
 * Видеодемо комнаты интервью. Ролик не хранится в репозитории: его пишет
 * Playwright-сценарий кандидата (E2E_VIDEO=1, см. public/demo/README.md) и
 * кладут в public/demo/interview-demo.mp4. Серверный компонент проверяет
 * наличие файла при рендере (для статической страницы — во время сборки) и
 * без него показывает заглушку-постер.
 */
export const DEMO_VIDEO_SRC = "/demo/interview-demo.mp4";
export const DEMO_POSTER_SRC = "/demo/poster.svg";

export function demoVideoExists(): boolean {
  return fs.existsSync(path.join(process.cwd(), "public", ...DEMO_VIDEO_SRC.split("/").filter(Boolean)));
}

const DEMO_CHAPTERS = ["Ссылка и согласия", "Проверка камеры", "Тренировочный вопрос", "Ответ с таймером", "Завершение"];

export function VideoDemo({ available = demoVideoExists() }: { available?: boolean }) {
  return (
    <Section
      id="demo"
      eyebrow="Видеодемо"
      title="Посмотрите, как выглядит интервью"
      lead="Запись сценария кандидата целиком: от ссылки до «Спасибо, интервью завершено!». Так вы будете знать каждый экран ещё до того, как включите камеру."
      tone="muted"
    >
      <div className="mx-auto max-w-4xl">
        {available ? (
          <video
            controls
            playsInline
            preload="metadata"
            poster={DEMO_POSTER_SRC}
            aria-label="Демо: как проходит видеоинтервью в LeonIT"
            className="aspect-video w-full rounded-2xl border bg-black"
            data-testid="demo-video"
          >
            <source src={DEMO_VIDEO_SRC} type="video/mp4" />
            Ваш браузер не воспроизводит видео. Вы можете{" "}
            <a href={DEMO_VIDEO_SRC} className="underline">
              открыть ролик отдельно
            </a>
            .
          </video>
        ) : (
          <DemoFrame
            caption="Демо появится после записи"
            hint="Ролик записывается автоматически из сквозного сценария кандидата"
            testId="demo-placeholder"
          />
        )}
        <ul className="mt-6 flex flex-wrap justify-center gap-2" aria-label="Что показано в демо">
          {DEMO_CHAPTERS.map((chapter, index) => (
            <li
              key={chapter}
              className="inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-xs text-muted-foreground"
            >
              <span className="font-mono text-primary">{index + 1}</span>
              {chapter}
            </li>
          ))}
        </ul>
      </div>
    </Section>
  );
}
