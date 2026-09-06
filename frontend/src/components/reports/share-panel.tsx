"use client";

import { Skeleton } from "@/components/ui/skeleton";

import { useCallback, useEffect, useState } from "react";
import { Link2, Users } from "lucide-react";

import { CopyField } from "@/components/candidates/invite-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
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
  const [loadError, setLoadError] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);

  const fail = useCallback(
    (error: unknown, fallback: string) =>
      toast({ variant: "destructive", title: error instanceof ApiError ? error.message : fallback }),
    [toast],
  );

  const load = useCallback(async () => {
    try {
      setShares(await reportsApi.shares(interviewId));
      setLoadError(false);
    } catch (error) {
      setLoadError(true);
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
    <Card className="report-share-panel rounded-[22px] border">
      <CardHeader>
        <CardTitle className="text-xl">Поделиться интервью</CardTitle>
        <CardDescription>
          Дайте нанимающему менеджеру доступ к ответам и отчёту этого кандидата. Выберите срок действия ссылки.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form className="report-share-form" onSubmit={event => { event.preventDefault(); void create(); }}>
          <div><Label htmlFor="share-recipient">Для кого</Label><Input id="share-recipient" placeholder="Например, руководитель команды" value={label} onChange={event => setLabel(event.target.value)} /></div>
          <div><Label htmlFor="share-days">Срок, дней</Label><Input id="share-days" type="number" min={1} max={90} required value={days} onChange={event => setDays(event.target.value)} /></div>
          <Button type="submit" disabled={pending || !Number.isInteger(Number(days)) || Number(days) < 1 || Number(days) > 90}>{pending ? <Skeleton className="h-4 w-4 rounded-md" /> : <Link2 size={17} />}Создать ссылку</Button>
        </form>
        {fresh ? (
          <div className="report-fresh-link">
            <p className="mb-2">Ссылка показывается один раз:</p>
            <CopyField value={fresh} />
          </div>
        ) : null}
        {loadError ? <div className="report-share-empty" role="alert"><p>Не удалось загрузить ссылки.</p><Button variant="outline" onClick={() => void load()}>Повторить</Button></div> : shares === null ? (
          <div className="space-y-3"><Skeleton className="h-16 rounded-xl" /><Skeleton className="h-16 rounded-xl" /></div>
        ) : shares.length ? (
          <ul className="report-share-list">
            {shares.map((share) => (
              <li key={share.id} className="report-share-row">
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
        ) : <div className="report-share-empty"><Users size={25} /><strong>Ссылок пока нет</strong><p>Создайте первую, чтобы обсудить кандидата с командой.</p></div>}
      </CardContent>
    </Card>
  );
}
