import Link from "next/link";
import { ArrowUpRight, Bot, Eye, FileCheck2, MailX, Timer } from "lucide-react";

import { IconChip, Section } from "@/components/landing/section";
import { CONTACT_EMAIL, LEGAL_DOCUMENTS, legalHref } from "@/lib/site";

/*
 * Факты о данных берутся из текстов согласия и политики
 * (backend/leonit/legal/documents): кто получает доступ, что уходит моделям,
 * сроки хранения и порядок отзыва.
 */
const FACTS = [
  {
    icon: FileCheck2,
    title: "Согласие — до первого вопроса",
    text: "Перед интервью вы подтверждаете согласие на обработку персональных данных, включая видео и голос, и знакомство с политикой конфиденциальности. Рассылка о вакансиях — отдельная галочка, по желанию.",
  },
  {
    icon: Eye,
    title: "Запись видят только по вакансии",
    text: "Доступ к видео, транскрипту и заключению есть у рекрутера и нанимающего менеджера этой вакансии — в пределах их ролей. Ссылка на отчёт для менеджера действует ограниченный срок, каждый просмотр записывается.",
  },
  {
    icon: Bot,
    title: "ИИ помогает, решает человек",
    text: "Моделям уходит аудио для расшифровки и текст, в котором имя, e-mail и телефон заменены плейсхолдерами. Видео и снимки с камеры им не передаются. ИИ готовит заключение по критериям вакансии, а решение принимает сотрудник компании.",
  },
  {
    icon: Timer,
    title: "Хранение ограничено по времени",
    text: "Видео и аудио ответов хранятся столько дней, сколько задала организация (обычно 180, не дольше года), и удаляются автоматически. Точный срок — в тексте согласия на вашей странице приглашения.",
  },
  {
    icon: MailX,
    title: "Согласие можно отозвать",
    text: `В любой момент напишите на ${CONTACT_EMAIL} с темой «Отзыв согласия — LeonIT» с адреса, который указали перед интервью. Данные удалят в срок, установленный законом.`,
  },
] as const;

export function DataPrivacy() {
  return (
    <Section
      id="privacy"
      eyebrow="Ваши данные"
      title="Что происходит с записью после интервью"
      lead="Коротко и без юридического языка. Полные тексты — в блоке «Документы» рядом."
      tone="muted"
    >
      <div className="grid gap-8 lg:grid-cols-[1.5fr_1fr]">
        <ul className="space-y-6">
          {FACTS.map((fact) => (
            <li key={fact.title} className="flex gap-4">
              <IconChip icon={fact.icon} />
              <div>
                <h3 className="font-semibold">{fact.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{fact.text}</p>
              </div>
            </li>
          ))}
        </ul>
        <aside aria-labelledby="privacy-docs-title" className="h-fit rounded-2xl border bg-card p-6 shadow-sm lg:sticky lg:top-24">
          <h3 id="privacy-docs-title" className="font-semibold">
            Документы
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Действующие редакции. На каждой странице указаны версия, дата и хеш текста — их же вы увидите в
            журнале согласий.
          </p>
          <ul className="mt-4 divide-y">
            {LEGAL_DOCUMENTS.map((doc) => (
              <li key={doc.slug}>
                <Link
                  href={legalHref(doc.slug)}
                  className="flex items-center justify-between gap-3 py-3 text-sm font-medium transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {doc.title}
                  <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </Section>
  );
}
