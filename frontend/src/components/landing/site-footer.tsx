import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { LANDING_NAV } from "@/components/landing/site-header";
import { CONTACT_EMAIL, LEGAL_DOCUMENTS, legalHref } from "@/lib/site";

const linkClass =
  "rounded-sm text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function SiteFooter() {
  return (
    <footer className="border-t bg-muted/40">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <Logo size={28} />
          <p className="mt-4 max-w-xs text-sm text-muted-foreground">
            Асинхронные видеоинтервью: кандидат отвечает в удобное время, рекрутер и нанимающий менеджер
            получают структурированное заключение.
          </p>
        </div>
        <nav aria-label="Кандидатам">
          <h2 className="text-sm font-semibold">Кандидатам</h2>
          <ul className="mt-3 space-y-2">
            {LANDING_NAV.filter((item) => item.href !== "#recruiters").map((item) => (
              <li key={item.href}>
                <a href={item.href} className={linkClass}>
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Юридические документы">
          <h2 className="text-sm font-semibold">Документы</h2>
          <ul className="mt-3 space-y-2">
            {LEGAL_DOCUMENTS.map((doc) => (
              <li key={doc.slug}>
                <Link href={legalHref(doc.slug)} className={linkClass}>
                  {doc.title}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div>
          <h2 className="text-sm font-semibold">Контакты</h2>
          <ul className="mt-3 space-y-2">
            <li>
              <a href={`mailto:${CONTACT_EMAIL}`} className={linkClass}>
                {CONTACT_EMAIL}
              </a>
            </li>
            <li>
              <Link href="/login" className={linkClass}>
                Войти в кабинет
              </Link>
            </li>
            <li>
              <Link href="/register" className={linkClass}>
                Для рекрутеров
              </Link>
            </li>
          </ul>
        </div>
      </div>
      <div className="border-t">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>© {new Date().getFullYear()} LeonIT · Napoleon IT</p>
          <p>Оператор персональных данных — ООО «Наполеон АйТи»</p>
        </div>
      </div>
    </footer>
  );
}
