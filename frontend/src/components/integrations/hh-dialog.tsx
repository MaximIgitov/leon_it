"use client";

import Link from "@/lib/router";
import { useEffect, useState } from "react";
import { Bot, User, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HH_DIALOG_STATE_LABELS, hhApi, type HhDialogMessage, type HhDialogState, type HhNegotiation } from "@/lib/api/hh";
import { cn } from "@/lib/utils";

const STATE_VARIANTS: Partial<Record<HhDialogState, "default" | "secondary" | "destructive" | "outline">> = {
  link_sent: "default",
  done: "default",
  declined: "destructive",
  needs_recruiter: "outline",
};

export function HhDialogStateBadge({ state }: { state: HhDialogState }) {
  return <Badge variant={STATE_VARIANTS[state] ?? "secondary"}>{HH_DIALOG_STATE_LABELS[state]}</Badge>;
}

function formatTime(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const ROLE_LABELS: Record<HhDialogMessage["role"], string> = {
  bot: "LeonIT",
  candidate: "Кандидат",
  recruiter: "Рекрутер",
};

/** История диалога в чате HH: пузырьки бота слева, кандидата — справа. */
export function HhDialogThread({ messages }: { messages: HhDialogMessage[] }) {
  if (messages.length === 0) {
    return <p className="text-sm text-muted-foreground">Сообщений ещё не было.</p>;
  }
  return (
    <ol className="space-y-3">
      {messages.map((message, index) => {
        const mine = message.role !== "candidate";
        const Icon = message.role === "bot" ? Bot : message.role === "recruiter" ? UserRound : User;
        return (
          <li key={message.hh_message_id ?? index} className={cn("flex gap-2", mine ? "justify-start" : "justify-end")}>
            {mine ? (
              <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center text-primary">
                <Icon className="h-4 w-4" />
              </span>
            ) : null}
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm",
                mine ? "rounded-tl-sm bg-secondary" : "rounded-tr-sm bg-accent text-accent-foreground",
              )}
            >
              <div className={cn("mb-0.5 text-[11px]", mine ? "text-muted-foreground" : "text-primary-foreground/80")}>
                {ROLE_LABELS[message.role]}
                {message.at ? ` · ${formatTime(message.at)}` : ""}
              </div>
              <p className="whitespace-pre-wrap break-words">{message.text}</p>
            </div>
            {!mine ? (
              <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center text-primary">
                <Icon className="h-4 w-4" />
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Карточка «Диалог с HH» для страницы кандидата. Рендерится только если у
 * кандидата есть отклик HH; без прав на интеграции (нанимающий менеджер) —
 * молча ничего не показывает.
 */
export function HhDialogCard({ candidateId }: { candidateId: string }) {
  const [items, setItems] = useState<HhNegotiation[]>([]);

  useEffect(() => {
    let cancelled = false;
    hhApi
      .negotiations({ candidate_id: candidateId })
      .then((list) => {
        if (!cancelled) setItems(list);
      })
      .catch(() => {
        /* нет доступа или интеграция не подключена — карточка не нужна */
      });
    return () => {
      cancelled = true;
    };
  }, [candidateId]);

  if (items.length === 0) return null;

  return (
    <>
      {items.map((item) => (
        <Card key={item.id}>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Диалог с HH</CardTitle>
              <CardDescription>
                Отклик на{" "}
                <Link href={`/vacancies/${item.vacancy_id}`} className="hover:underline">
                  {item.vacancy_title}
                </Link>
                {item.chosen_date
                  ? ` · выбранный день: ${new Date(item.chosen_date).toLocaleDateString("ru-RU")}`
                  : ""}
              </CardDescription>
            </div>
            <HhDialogStateBadge state={item.state} />
          </CardHeader>
          <CardContent>
            <HhDialogThread messages={item.messages} />
            {item.last_error ? <p className="mt-3 text-xs text-destructive">{item.last_error}</p> : null}
          </CardContent>
        </Card>
      ))}
    </>
  );
}
