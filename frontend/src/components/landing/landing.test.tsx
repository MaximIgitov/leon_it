import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import robots from "@/app/robots";
import sitemap from "@/app/sitemap";
import { FAQ_ITEMS } from "@/components/landing/faq";
import { LANDING_NAV } from "@/components/landing/site-header";
import { VideoDemo } from "@/components/landing/video-demo";
import { CONTACT_EMAIL, LEGAL_DOCUMENTS } from "@/lib/site";

/*
 * Лендинг — статическая разметка без данных, поэтому рендерим его напрямую
 * через react-dom/server и проверяем секции, ссылки, порядок заголовков и
 * блок демо. Ссылки TanStack Router требуют контекст роутера, которого в
 * серверном рендере нет, — подменяем обёртку обычным <a href>.
 */
vi.mock("@/lib/router", async () => {
  const { createElement } = await import("react");
  return {
    default: ({ href, ...props }: { href: string }) => createElement("a", { href, ...props }),
    usePathname: () => "/",
    useParams: () => ({}),
    useSearchParams: () => new URLSearchParams(),
    useRouter: () => ({ push: () => undefined, replace: () => undefined }),
  };
});

function headingLevels(html: string): number[] {
  return Array.from(html.matchAll(/<h([1-6])[\s>]/g), (match) => Number(match[1]));
}

describe("лендинг", () => {
  it("рендерит основные секции и навигацию к ним", () => {
    const html = renderToStaticMarkup(<HomePage />);

    expect(html).toContain('<main id="main"');
    for (const id of ["how-it-works", "demo", "recruiters", "faq"]) {
      expect(html).toContain(`id="${id}"`);
      expect(html).toContain(`href="#${id}"`);
    }
    for (const item of LANDING_NAV) {
      expect(html).toContain(`href="${item.href}"`);
      expect(html).toContain(item.label);
    }
    expect(html).toContain("Познакомься");
    expect(html).toContain("Всего три простых шага");
    expect(html).toContain("Отчёт по каждому интервью");
    expect(html).toContain("Решение за человеком");
  });

  it("ведёт рекрутеров в кабинет, кандидатов — к тренировке, документам и контакту", () => {
    const html = renderToStaticMarkup(<HomePage />);

    expect(html).toContain('href="/login"');
    expect(html).toContain('href="/register"');
    expect(html).toContain('href="/practice"');
    expect(html).toContain("Создать вакансию");
    for (const doc of LEGAL_DOCUMENTS) {
      expect(html).toContain(`href="/legal/${doc.slug}"`);
      expect(html).toContain(doc.title);
    }
    expect(html).toContain(`href="mailto:${CONTACT_EMAIL}"`);
  });

  it("держит заголовки по порядку: один h1, без пропуска уровней", () => {
    const levels = headingLevels(renderToStaticMarkup(<HomePage />));

    expect(levels[0]).toBe(1);
    expect(levels.filter((level) => level === 1)).toHaveLength(1);
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
    }
  });

  it("содержит FAQ из 6–8 вопросов, и все они попадают на страницу", () => {
    const html = renderToStaticMarkup(<HomePage />);

    expect(FAQ_ITEMS.length).toBeGreaterThanOrEqual(6);
    expect(FAQ_ITEMS.length).toBeLessThanOrEqual(8);
    for (const item of FAQ_ITEMS) {
      expect(html).toContain(item.question);
    }
    expect(html).toContain("Можно ли перезаписать ответ?");
    expect(html).toContain("Кто принимает решение?");
  });

  it("блок демо предлагает пробный вопрос и запуск ролика, пока видео не включено", () => {
    const html = renderToStaticMarkup(<VideoDemo />);

    expect(html).toContain('id="demo"');
    expect(html).toContain("Пробный вопрос");
    expect(html).toContain('aria-label="Посмотреть видео интервью"');
    expect(html).toContain('href="/practice"');
    expect(html).not.toContain("<video");
  });

  it("без записи демо кнопка просмотра ролика не показывается", () => {
    const html = renderToStaticMarkup(<VideoDemo available={false} />);

    expect(html).toContain("Пробный вопрос");
    expect(html).not.toContain('aria-label="Посмотреть видео интервью"');
    expect(html).not.toContain("<video");
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
