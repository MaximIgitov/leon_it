"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, MailX, XCircle } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiFetch } from "@/lib/api/client";

type State = "idle" | "loading" | "done" | "already" | "error";

/*
 * Страница отписки по ссылке из письма. Отписка — действие, меняющее данные,
 * поэтому она не выполняется автоматически при открытии: почтовые клиенты и
 * антивирусы «прокликивают» ссылки заранее, и человек оказался бы отписан, даже
 * не открыв письмо. Кнопка подтверждения — один явный шаг.
 */
export default function UnsubscribePage() {
  const params = useParams<{ token: string }>();
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Отписка от писем — LeonIT";
  }, []);

  const unsubscribe = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const result = await apiFetch<{ already: boolean }>(
        `/public/unsubscribe/${encodeURIComponent(params.token)}`,
        { method: "POST" },
      );
      setState(result.already ? "already" : "done");
    } catch (caught) {
      setState("error");
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Не получилось отписаться. Попробуйте позже или напишите нам.",
      );
    }
  }, [params.token]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4 py-12">
      <Link href="/" aria-label="LeonIT — на главную">
        <Logo size={30} />
      </Link>
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <MailX className="h-5 w-5 text-muted-foreground" aria-hidden />
            Отписка от писем LeonIT
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          {state === "done" || state === "already" ? (
            <p className="flex items-start gap-2 text-foreground">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
              {state === "done"
                ? "Готово: писем от LeonIT больше не будет. Приглашения на интервью от компаний, куда вы откликнулись, это не отменяет."
                : "Вы уже отписаны — новых писем не приходит."}
            </p>
          ) : (
            <>
              <p className="text-muted-foreground">
                Подтвердите отписку, и мы перестанем отправлять письма с обратной связью по
                интервью и другие письма LeonIT.
              </p>
              {state === "error" && error ? (
                <p className="flex items-start gap-2 text-destructive">
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  {error}
                </p>
              ) : null}
              <Button onClick={unsubscribe} disabled={state === "loading"}>
                {state === "loading" ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                    Отписываем…
                  </>
                ) : (
                  "Отписаться от писем"
                )}
              </Button>
            </>
          )}
          <p className="text-xs text-muted-foreground">
            Передумали? Просто закройте страницу — ничего не изменится.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
