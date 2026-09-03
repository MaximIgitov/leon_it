import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";

export const LANDING_NAV = [
  { href: "#how", label: "Как проходит" },
  { href: "#demo", label: "Демо" },
  { href: "#requirements", label: "Что нужно" },
  { href: "#privacy", label: "Ваши данные" },
  { href: "#faq", label: "Вопросы" },
  { href: "#recruiters", label: "Рекрутерам" },
] as const;

/** Шапка публичных страниц: логотип, якорная навигация, вход для рекрутеров. */
export function SiteHeader() {
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Перейти к содержимому
      </a>
      <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/70">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <Link href="/" aria-label="LeonIT — на главную" className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
            <Logo size={30} />
          </Link>
          <nav aria-label="Разделы страницы" className="hidden items-center gap-1 lg:flex">
            {LANDING_NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {item.label}
              </a>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/login">Войти</Link>
            </Button>
            <Button size="sm" asChild>
              <Link href="/register">Для рекрутеров</Link>
            </Button>
          </div>
        </div>
      </header>
    </>
  );
}
