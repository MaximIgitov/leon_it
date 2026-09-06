"use client";

import { Skeleton } from "@/components/ui/skeleton";

import Link from "@/lib/router";
import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, Send } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import {
  describePush,
  huntflowApi,
  isPushInFlight,
  type HuntflowConnection,
  type HuntflowPush,
} from "@/lib/api/huntflow";

const POLL_INTERVAL_MS = 2000;
const POLL_LIMIT = 60;

/**
 * Кнопка «В Huntflow» для карточки кандидата.
 *
 * Показывается только при активном подключении Huntflow; после запуска передачи
 * опрашивает статус, пока задача в очереди или выполняется.
 */
export function HuntflowPush({ candidateId }: { candidateId: string }) {
  const { can } = useAuth();
  const { toast } = useToast();
  const [connection, setConnection] = useState<HuntflowConnection | null>(null);
  const [push, setPush] = useState<HuntflowPush | null>(null);
  const [pending, setPending] = useState(false);
  const polls = useRef(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await huntflowApi.status();
        if (cancelled || !status.connected || status.status !== "active") return;
        setConnection(status);
        setPush(await huntflowApi.pushStatus(candidateId));
      } catch {
        /* нет прав или интеграция не подключена — кнопка не показывается */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [candidateId]);

  const inFlight = push !== null && isPushInFlight(push.status);

  const refresh = useCallback(async () => {
    try {
      setPush(await huntflowApi.pushStatus(candidateId));
    } catch {
      /* временная ошибка — следующий опрос повторит */
    }
  }, [candidateId]);

  useEffect(() => {
    if (!inFlight) {
      polls.current = 0;
      return;
    }
    const timer = window.setInterval(() => {
      polls.current += 1;
      if (polls.current > POLL_LIMIT) {
        window.clearInterval(timer);
        return;
      }
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [inFlight, refresh]);

  useEffect(() => {
    if (push?.status === "pushed" && polls.current > 0) {
      toast({ title: "Кандидат передан в Huntflow" });
      polls.current = 0;
    }
  }, [push?.status, toast]);

  if (!connection || !can("candidate.write")) return null;

  const send = async () => {
    setPending(true);
    try {
      setPush(await huntflowApi.push(candidateId));
    } catch (error) {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Не удалось передать кандидата",
      });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" onClick={send} disabled={pending || inFlight}>
        {pending || inFlight ? (
          <Skeleton className="mr-2 h-4 w-4 rounded-md" />
        ) : (
          <Send className="mr-2 h-4 w-4" />
        )}
        В Huntflow
      </Button>
      <span
        className={
          push?.status === "error" ? "text-xs text-destructive" : "text-xs text-muted-foreground"
        }
        title={push?.last_error ?? undefined}
      >
        {describePush(push)}
      </span>
      {push?.report_share_url ? (
        <Link
          href={push.report_share_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          отчёт
          <ExternalLink className="h-3 w-3" />
        </Link>
      ) : null}
      {connection.mode === "fake" ? <Badge variant="secondary">Демо</Badge> : null}
    </div>
  );
}
