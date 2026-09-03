import Link from "next/link";
import { ArrowRight, Briefcase, ClipboardList, Link2 } from "lucide-react";

import { Button } from "@/components/ui/button";

const STEPS = [
  {
    icon: Briefcase,
    title: "Вакансия",
    text: "Требования, вопросы и рубрика по компетенциям. Ассистент предложит черновик, вы поправите.",
  },
  {
    icon: Link2,
    title: "Ссылка",
    text: "Персональное приглашение со сроком. Кандидат проходит интервью, когда ему удобно, без согласования слотов.",
  },
  {
    icon: ClipboardList,
    title: "Заключение",
    text: "Транскрипт, оценки по критериям с цитатами, сильные стороны, риски и рекомендация. Решение — за вами.",
  },
] as const;

export function ForRecruiters() {
  return (
    <section id="recruiters" aria-labelledby="recruiters-title" className="scroll-mt-20 py-16 sm:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="overflow-hidden rounded-3xl bg-primary px-6 py-10 text-primary-foreground sm:px-10 sm:py-14">
          <div className="grid gap-10 lg:grid-cols-[1fr_1.2fr] lg:items-center">
            <div>
              <p className="text-sm font-semibold opacity-80">Рекрутерам и нанимающим менеджерам</p>
              <h2 id="recruiters-title" className="mt-2 text-balance text-3xl font-bold tracking-tight sm:text-4xl">
                {"Вакансия → ссылка → структурированное заключение"}
              </h2>
              <p className="mt-4 text-pretty opacity-90">
                Первичный отбор без десятков созвонов. Каждый кандидат отвечает на одни и те же вопросы, а вы
                сравниваете их по одной рубрике и смотрите видео только там, где это нужно.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Button size="lg" variant="secondary" asChild className="bg-background text-foreground hover:bg-background/90">
                  <Link href="/register">
                    Для рекрутеров
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                </Button>
                <Button
                  size="lg"
                  variant="outline"
                  asChild
                  className="border-primary-foreground/40 bg-transparent text-primary-foreground hover:bg-primary-foreground/10 hover:text-primary-foreground"
                >
                  <Link href="/login">Войти в кабинет</Link>
                </Button>
              </div>
            </div>
            <ol className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
              {STEPS.map((step, index) => (
                <li key={step.title} className="rounded-2xl bg-primary-foreground/10 p-5 backdrop-blur-sm">
                  <div className="flex items-center gap-3">
                    <span
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-foreground/15"
                      aria-hidden="true"
                    >
                      <step.icon className="h-4 w-4" />
                    </span>
                    <h3 className="font-semibold">
                      <span className="sr-only">Шаг {index + 1}: </span>
                      {step.title}
                    </h3>
                  </div>
                  <p className="mt-3 text-sm opacity-90">{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </section>
  );
}
