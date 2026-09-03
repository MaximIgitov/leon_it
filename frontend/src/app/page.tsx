import type { Metadata } from "next";

import { DataPrivacy } from "@/components/landing/data-privacy";
import { Faq } from "@/components/landing/faq";
import { ForRecruiters } from "@/components/landing/for-recruiters";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { Requirements } from "@/components/landing/requirements";
import { SiteFooter } from "@/components/landing/site-footer";
import { SiteHeader } from "@/components/landing/site-header";
import { VideoDemo } from "@/components/landing/video-demo";

/*
 * Лендинг для соискателей: человек получил ссылку на интервью и хочет понять,
 * что его ждёт. Вторичная аудитория — рекрутеры (вход и регистрация в шапке
 * и в блоке «Рекрутерам»). Страница статическая, без клиентского JS:
 * все секции — серверные компоненты в components/landing.
 */

const TITLE = "LeonIT — видеоинтервью в удобное для вас время";
const DESCRIPTION =
  "Получили ссылку на интервью LeonIT? Узнайте, как оно проходит: вопросы озвучиваются, ответы записываются по одному, без созвона и регистрации. Что подготовить, кто увидит запись и как получить обратную связь.";

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    locale: "ru_RU",
    siteName: "LeonIT",
    title: TITLE,
    description: DESCRIPTION,
    url: "/",
  },
  twitter: {
    card: "summary",
    title: TITLE,
    description: DESCRIPTION,
  },
};

export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <SiteHeader />
      <main id="main" className="flex-1">
        <Hero />
        <HowItWorks />
        <VideoDemo />
        <Requirements />
        <DataPrivacy />
        <Faq />
        <ForRecruiters />
      </main>
      <SiteFooter />
    </div>
  );
}
