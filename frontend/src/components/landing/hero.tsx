import { ArrowRight, Clock3, Play, Smartphone, UserRoundCheck, Video } from "lucide-react";

import { RoomPreview } from "@/components/landing/illustrations";
import { Button } from "@/components/ui/button";

const FACTS = [
  { icon: Clock3, text: "10–20 минут, когда удобно вам" },
  { icon: UserRoundCheck, text: "Без регистрации и созвона" },
  { icon: Smartphone, text: "С компьютера или телефона" },
] as const;

export function Hero() {
  return (
    <section aria-labelledby="hero-title" className="relative overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-[-160px] h-[520px] bg-[radial-gradient(60%_100%_at_50%_0%,hsl(var(--primary)/0.14),transparent)]"
      />
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-16 pt-14 sm:px-6 sm:pt-20 lg:grid-cols-[1.1fr_1fr] lg:gap-16 lg:pb-24 lg:pt-24">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border bg-card px-4 py-1.5 text-sm text-muted-foreground">
            <Video className="h-4 w-4 text-primary" aria-hidden="true" />
            Видеоинтервью для кандидатов
          </p>
          <h1
            id="hero-title"
            className="mt-6 text-balance text-4xl font-bold leading-[1.1] tracking-tight sm:text-5xl lg:text-6xl"
          >
            Интервью, которое <span className="text-primary">не нужно назначать</span>
          </h1>
          <p className="mt-6 max-w-xl text-pretty text-lg text-muted-foreground">
            Вам прислали ссылку на видеоинтервью LeonIT? Это не созвон. Вопросы озвучиваются, вы отвечаете
            на камеру по одному и в своём темпе. Ответы увидят рекрутер и нанимающий менеджер, а вы получите
            честную обратную связь.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <Button size="lg" asChild>
              <a href="#how">
                Как проходит интервью
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </a>
            </Button>
            <Button size="lg" variant="outline" asChild>
              <a href="#demo">
                <Play className="h-4 w-4" aria-hidden="true" />
                Смотреть демо
              </a>
            </Button>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            Ссылку на интервью присылает рекрутер компании — здесь её получить нельзя. Если письма нет,
            проверьте папку «Спам».
          </p>
          <ul className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:gap-x-6">
            {FACTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-2 text-sm">
                <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                {text}
              </li>
            ))}
          </ul>
        </div>
        <RoomPreview className="mx-auto w-full max-w-xl lg:max-w-none" />
      </div>
    </section>
  );
}
