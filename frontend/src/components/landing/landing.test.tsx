import fs from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import robots from "@/app/robots";
import sitemap from "@/app/sitemap";
import { FAQ_ITEMS } from "@/components/landing/faq";
import { DEMO_VIDEO_SRC, VideoDemo, demoVideoExists } from "@/components/landing/video-demo";
import { LEGAL_DOCUMENTS } from "@/lib/site";

/*
 * Лендинг — статические серверные компоненты, поэтому рендерим их напрямую
 * через react-dom/server и проверяем разметку: секции, ссылки, порядок
 * заголовков и заглушку видео.
 */

function headingLevels(html: string): number[] {
  return Array.from(html.matchAll(/<h([1-6])[\s>]/g), (match) => Number(match[1]));
}

describe("лендинг", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("рендерит основные секции и навигацию к ним", () => {
    const html = renderToStaticMarkup(<HomePage />);

    expect(html).toContain('<main id="main"');
    for (const id of ["how", "demo", "requirements", "privacy", "faq", "recruiters"]) {
      expect(html).toContain(`id="${id}"`);
      expect(html).toContain(`href="#${id}"`);
    }
    expect(html).toContain("Интервью, которое");
    expect(html).toContain("Как проходит интервью");
    expect(html).toContain("Что нужно для интервью");
    expect(html).toContain("Ваши данные");
    expect(html).toContain("Частые вопросы");
    expect(html).toContain("структурированное заключение");
  });

  it("ведёт рекрутеров в кабинет, а кандидатов — к документам и контакту", () => {
    const html = renderToStaticMarkup(<HomePage />);

    expect(html).toContain('href="/login"');
    expect(html).toContain('href="/register"');
    expect(html).toContain("Для рекрутеров");
    for (const doc of LEGAL_DOCUMENTS) {
      expect(html).toContain(`href="/legal/${doc.slug}"`);
    }
    expect(html).toContain('href="mailto:info@napoleonit.ru"');
  });

  it("держит заголовки по порядку: один h1, без пропуска уровней", () => {
    const levels = headingLevels(renderToStaticMarkup(<HomePage />));

    expect(levels[0]).toBe(1);
    expect(levels.filter((level) => level === 1)).toHaveLength(1);
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
    }
  });

  it("содержит FAQ из 6–8 раскрывающихся вопросов", () => {
    const html = renderToStaticMarkup(<HomePage />);
    const details = html.match(/<details/g) ?? [];

    expect(FAQ_ITEMS.length).toBeGreaterThanOrEqual(6);
    expect(FAQ_ITEMS.length).toBeLessThanOrEqual(8);
    expect(details).toHaveLength(FAQ_ITEMS.length);
    expect(html).toContain("Можно ли перезаписать ответ?");
    expect(html).toContain("Ссылка одноразовая?");
  });

  it("показывает заглушку, когда демо-видео ещё не записано", () => {
    // Наличие файла проверяется на диске, поэтому подменяем его: тест про
    // поведение лендинга, а не про то, лежит ли запись в репозитории.
    vi.spyOn(fs, "existsSync").mockReturnValue(false);
    expect(demoVideoExists()).toBe(false);
    const html = renderToStaticMarkup(<VideoDemo />);

    expect(html).toContain('data-testid="demo-placeholder"');
    expect(html).toContain("Демо появится после записи");
    expect(html).not.toContain("<video");
  });

  it("на главной есть блок демо: плеер, когда запись лежит в public/demo", () => {
    const html = renderToStaticMarkup(<HomePage />);

    expect(html).toContain('id="demo"');
    expect(html).toContain(demoVideoExists() ? 'data-testid="demo-video"' : 'data-testid="demo-placeholder"');
  });

  it("показывает плеер с постером, когда файл есть", () => {
    vi.spyOn(fs, "existsSync").mockReturnValue(true);
    const html = renderToStaticMarkup(<VideoDemo />);

    expect(html).toContain('data-testid="demo-video"');
    expect(html).toContain("<video");
    expect(html).toContain("controls");
    expect(html).toContain('poster="/demo/poster.svg"');
    expect(html).toContain(`src="${DEMO_VIDEO_SRC}"`);
    expect(html).not.toContain("Демо появится после записи");
  });

  it("робот-правила и sitemap покрывают главную и юридические страницы", () => {
    const robotRules = robots();
    const rules = Array.isArray(robotRules.rules) ? robotRules.rules : [robotRules.rules];
    const disallow = rules.flatMap((rule) => rule.disallow ?? []);
    expect(disallow).toEqual(expect.arrayContaining(["/i/", "/r/", "/join"]));
    expect(robotRules.sitemap).toMatch(/\/sitemap\.xml$/);

    const urls = sitemap().map((entry) => new URL(entry.url).pathname);
    expect(urls).toContain("/");
    for (const doc of LEGAL_DOCUMENTS) {
      expect(urls).toContain(`/legal/${doc.slug}`);
    }
  });
});
