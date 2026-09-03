import Link from "next/link";
import { ArrowRight, Clock3, ShieldCheck, Video } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";

/*
 * Временная главная страница: сюда встанет лендинг для соискателей с видеодемо
 * (PR 21). Пока — короткое объяснение, что это за сервис, и вход в кабинет.
 */
export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link href="/" aria-label="LeonIT — на главную">
            <Logo size={30} />
          </Link>
          <div className="flex items-center gap-2">
            <Button variant="ghost" asChild>
              <Link href="/login">Войти</Link>
            </Button>
            <Button asChild>
              <Link href="/register">Для рекрутеров</Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1">
        <section className="relative overflow-hidden">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-[-200px] h-[480px] bg-[radial-gradient(60%_100%_at_50%_0%,hsl(var(--primary)/0.12),transparent)]"
          />
          <div className="mx-auto max-w-6xl px-4 pb-20 pt-20 text-center sm:px-6 sm:pt-28">
            <p className="inline-flex items-center gap-2 rounded-full border bg-card px-4 py-1.5 text-sm text-muted-foreground">
              <Video className="h-4 w-4 text-primary" />
              Техническое интервью онлайн
            </p>
            <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-bold leading-tight tracking-tight sm:text-6xl">
              Пройдите интервью{" "}
              <span className="text-primary">когда удобно вам</span>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
              Никаких согласований слотов. Откройте ссылку, включите камеру и ответьте
              на вопросы — результат увидят рекрутер и нанимающий менеджер.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <Button size="lg" asChild className="gap-2">
                <Link href="/register">
                  Начать
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </div>

            <dl className="mx-auto mt-16 grid max-w-4xl grid-cols-1 gap-4 text-left sm:grid-cols-3">
              {[
                [Clock3, "В удобное время", "Интервью доступно круглосуточно, из любого места."],
                [Video, "С камерой и голосом", "Вопросы озвучиваются, ответы записываются по одному."],
                [ShieldCheck, "Честная оценка", "Структурированное заключение по требованиям вакансии."],
              ].map(([Icon, title, text]) => {
                const IconComponent = Icon as React.ElementType;
                return (
                  <div key={String(title)} className="rounded-xl border bg-card p-6">
                    <div className="w-fit rounded-lg bg-primary/10 p-2.5">
                      <IconComponent className="h-5 w-5 text-primary" />
                    </div>
                    <dt className="mt-4 font-semibold">{String(title)}</dt>
                    <dd className="mt-2 text-sm text-muted-foreground">{String(text)}</dd>
                  </div>
                );
              })}
            </dl>
          </div>
        </section>
      </main>

      <footer className="border-t py-8 text-center text-sm text-muted-foreground">
        © {new Date().getFullYear()} LeonIT
      </footer>
    </div>
  );
}
