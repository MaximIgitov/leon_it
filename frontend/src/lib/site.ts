/*
 * Общие константы публичной части сайта: адрес, контакты, юридические
 * документы. Используются лендингом, robots.ts и sitemap.ts.
 */

export const SITE_URL = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

export const CONTACT_EMAIL = "info@napoleonit.ru";

/** Slug-и совпадают с документами бэкенда (`GET /api/legal/{slug}`). */
export const LEGAL_DOCUMENTS = [
  { slug: "privacy-policy", title: "Политика конфиденциальности" },
  { slug: "personal-data-consent", title: "Согласие на обработку персональных данных" },
  { slug: "newsletter-consent", title: "Согласие на получение рассылки" },
  { slug: "processors", title: "Перечень обработчиков" },
] as const;

export type LegalSlug = (typeof LEGAL_DOCUMENTS)[number]["slug"];

export function legalHref(slug: LegalSlug): string {
  return `/legal/${slug}`;
}
