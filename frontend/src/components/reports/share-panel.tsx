"use client";

import { useCallback, useEffect, useState } from "react";
import { Link2, Loader2 } from "lucide-react";

import { CopyField } from "@/components/candidates/invite-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import { reportsApi, type Share } from "@/lib/api/reports";

const STATUS: Record<Share["status"], string> = { active: "действует", expired: "истекла", revoked: "отозвана" };

export function SharePanel({ interviewId }: { interviewId: string }) {
  const { toast } = useToast();
  const [shares, setShares] = useState<Share[] | null>(null);
  const [label, setLabel] = useState("");
  const [days, setDays] = useState("14");
  const [pending, setPending] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);

  const fail = useCallback(
    (error: unknown, fallback: string) =>
      toast({ variant: "destructive", title: error instanceof ApiError ? error.message : fallback }),
    [toast],
  );

  const load = useCallback(async () => {
    try {
      setShares(await reportsApi.shares(interviewId));
    } catch (error) {
      fail(error, "Не удалось загрузить ссылки");
    }
  }, [interviewId, fail]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    setPending(true);
    try {
      const share = await reportsApi.createShare(interviewId, { label, expires_in_days: Number(days) });
      setFresh(share.url);
      setLabel("");
      await load();
    } catch (error) {
      fail(error, "Не удалось создать ссылку");
    } finally {
      setPending(false);
    }
  };

  const revoke = async (id: string) => {
    try {
      await reportsApi.revokeShare(interviewId, id);
      await load();
    } catch (error) {
      fail(error, "Не удалось отозвать ссылку");
    }
  };

  const extend = async (id: string) => {
    try {
      await reportsApi.extendShare(interviewId, id, 14);
      await load();
    } catch (error) {
      fail(error, "Не удалось продлить ссылку");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Ссылка для нанимающего менеджера</CardTitle>
        <CardDescription>
          Открывает только этого кандидата, без других кандидатов и деталей integrity. Каждый
          просмотр и решение по ссылке записываются.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <Input
            placeholder="Кому (например, Тимлид Петров)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="min-w-[200px] flex-1"
          />
          <Input
            type="number"
            min={1}
            max={90}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            className="w-24"
            aria-label="Срок, дней"
          />
          <Button onClick={create} disabled={pending}>
            {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Link2 className="mr-2 h-4 w-4" />}
            Создать
          </Button>
        </div>
        {fresh ? (
          <div className="rounded-lg bg-muted/40 p-3 text-sm">
            <p className="mb-2">Ссылка показывается один раз:</p>
            <CopyField value={fresh} />
          </div>
        ) : null}
        {shares === null ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : shares.length ? (
          <ul className="divide-y text-sm">
            {shares.map((share) => (
              <li key={share.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div>
                  <span className="font-medium">{share.label || "Без подписи"}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    до {new Date(share.expires_at).toLocaleDateString("ru-RU")} · просмотров: {share.view_count}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={share.status === "active" ? "default" : "secondary"}>{STATUS[share.status]}</Badge>
                  {share.status === "active" ? (
                    <Button variant="ghost" size="sm" onClick={() => revoke(share.id)}>
                      Отозвать
                    </Button>
                  ) : (
                    <Button variant="ghost" size="sm" onClick={() => extend(share.id)}>
                      Продлить на 14 дней
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
