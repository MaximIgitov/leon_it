"use client";

import { RowsSkeleton, Skeleton } from "@/components/ui/skeleton";

import { useCallback, useEffect, useState } from "react";
import Link from "@/lib/router";
import { ArrowRight, BookOpen, KeyRound, Plus } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Mascot } from "@/components/brand/mascot";
import { CopyField } from "@/components/candidates/invite-dialog";
import { PageHeader } from "@/components/layout/page-header";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { API_BASE_URL, ApiError } from "@/lib/api/client";
import {
  API_DOCS_URL,
  API_SCOPES,
  TOKEN_STATUS_LABELS,
  tokensApi,
  type ApiScope,
  type ApiToken,
  type ApiTokenCreated,
} from "@/lib/api/tokens";

const EXPIRY_OPTIONS: { value: string; label: string }[] = [
  { value: "never", label: "Бессрочно" },
  { value: "30", label: "30 дней" },
  { value: "90", label: "90 дней" },
  { value: "180", label: "180 дней" },
  { value: "365", label: "1 год" },
];

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function useErrorToast() {
  const { toast } = useToast();
  return useCallback(
    (error: unknown, fallback: string) => {
      toast({ variant: "destructive", title: error instanceof ApiError ? error.message : fallback });
    },
    [toast],
  );
}

function DocsLink() {
  return (
    <Button asChild variant="outline">
      <a href={API_DOCS_URL} target="_blank" rel="noreferrer">
        <BookOpen className="mr-2 h-4 w-4" />
        Документация API
      </a>
    </Button>
  );
}

function CreateTokenDialog({ onCreated }: { onCreated: (token: ApiToken) => void }) {
  const showError = useErrorToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiScope[]>(["vacancies:read", "interviews:read"]);
  const [expiry, setExpiry] = useState("never");
  const [pending, setPending] = useState(false);
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);

  const reset = () => {
    setCreated(null);
    setName("");
    setScopes(["vacancies:read", "interviews:read"]);
    setExpiry("never");
  };

  const toggle = (scope: ApiScope, checked: boolean) => {
    setScopes((current) =>
      checked ? [...current.filter((s) => s !== scope), scope] : current.filter((s) => s !== scope),
    );
  };

  const submit = async () => {
    setPending(true);
    try {
      const token = await tokensApi.create({
        name: name.trim(),
        scopes,
        expires_in_days: expiry === "never" ? null : Number(expiry),
      });
      setCreated(token);
      onCreated(token);
    } catch (error) {
      showError(error, "Не удалось создать токен");
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          Новый токен
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>API-токен</DialogTitle>
          <DialogDescription>
            Токен даёт интеграции доступ только к выбранным областям. Его можно отозвать в любой
            момент.
          </DialogDescription>
        </DialogHeader>
        {created ? (
          <div className="space-y-3">
            <p className="text-sm">
              Токен создан. Он показывается <strong>один раз</strong> — скопируйте и сохраните в
              секретах интеграции. Потерянный токен нужно отозвать и выпустить новый.
            </p>
            <CopyField value={created.token} />
            <p className="text-xs text-muted-foreground">
              Передавайте его в заголовке <code>Authorization: Bearer {created.token_prefix}…</code>
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="token-name">Название</Label>
              <Input
                id="token-name"
                placeholder="Huntflow, HR-бот, скрипт импорта"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Области доступа</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {API_SCOPES.map((scope) => {
                  const id = `scope-${scope.value}`;
                  return (
                    <div
                      key={scope.value}
                      className="flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 text-sm hover:bg-secondary/50"
                    >
                      <Checkbox
                        id={id}
                        aria-labelledby={`${id}-label`}
                        className="mt-0.5"
                        checked={scopes.includes(scope.value)}
                        onCheckedChange={(checked) => toggle(scope.value, checked === true)}
                      />
                      <span>
                        <span id={`${id}-label`} className="font-medium">{scope.label}</span>
                        <span className="block text-xs text-muted-foreground">
                          {scope.description}
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="space-y-2">
              <Label>Срок действия</Label>
              <Select value={expiry} onValueChange={setExpiry}>
                <SelectTrigger className="w-[200px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXPIRY_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
        <DialogFooter>
          {created ? (
            <Button onClick={() => setOpen(false)}>Готово</Button>
          ) : (
            <Button onClick={submit} disabled={pending || !name.trim() || scopes.length === 0}>
              {pending ? (
                <Skeleton className="mr-2 h-4 w-4 rounded-md" />
              ) : (
                <KeyRound className="mr-2 h-4 w-4" />
              )}
              Создать токен
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevokeButton({ token, onRevoked }: { token: ApiToken; onRevoked: (token: ApiToken) => void }) {
  const showError = useErrorToast();
  const [pending, setPending] = useState(false);

  const revoke = async () => {
    setPending(true);
    try {
      onRevoked(await tokensApi.revoke(token.id));
    } catch (error) {
      showError(error, "Не удалось отозвать токен");
    } finally {
      setPending(false);
    }
  };

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="sm" disabled={pending}>
          Отозвать
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Отозвать токен «{token.name}»?</AlertDialogTitle>
          <AlertDialogDescription>
            Интеграция, которая им пользуется, сразу начнёт получать 401. Отзыв необратим —
            вместо него можно выпустить новый токен.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={revoke}>Отозвать</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function ScopeBadges({ scopes }: { scopes: ApiScope[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {scopes.map((scope) => (
        <Badge key={scope} variant="outline" className="font-mono text-[11px]">
          {scope}
        </Badge>
      ))}
    </div>
  );
}

function ApiTokensCard() {
  const showError = useErrorToast();
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);

  const load = useCallback(async () => {
    try {
      setTokens(await tokensApi.list());
    } catch (error) {
      showError(error, "Не удалось загрузить токены");
    }
  }, [showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const replace = (updated: ApiToken) =>
    setTokens((current) => current?.map((t) => (t.id === updated.id ? updated : t)) ?? null);

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>API-токены</CardTitle>
          <CardDescription>
            Токены выпускает владелец организации. Сам токен виден только при создании — в списке
            остаётся его начало.
          </CardDescription>
        </div>
        <CreateTokenDialog onCreated={(token) => setTokens((c) => [token, ...(c ?? [])])} />
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        {tokens === null ? (
          <div className="p-6">
            <RowsSkeleton />
          </div>
        ) : tokens.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">
            Токенов пока нет. Создайте первый, чтобы подключить ATS или скрипт.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Токен</TableHead>
                <TableHead>Области</TableHead>
                <TableHead>Использован</TableHead>
                <TableHead>Действует до</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.map((token) => (
                <TableRow key={token.id} className={token.status === "active" ? "" : "opacity-60"}>
                  <TableCell>
                    <div className="font-medium">{token.name}</div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {token.token_prefix}…
                    </div>
                  </TableCell>
                  <TableCell>
                    <ScopeBadges scopes={token.scopes} />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDate(token.last_used_at)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {token.expires_at ? formatDate(token.expires_at) : "бессрочно"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={token.status === "active" ? "default" : "secondary"}>
                      {TOKEN_STATUS_LABELS[token.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {token.status === "active" ? (
                      <RevokeButton token={token} onRevoked={replace} />
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function QuickStartCard() {
  const example = [
    `curl ${API_BASE_URL}/v1/vacancies?status=published \\`,
    `  -H "Authorization: Bearer leonit_<токен>"`,
  ].join("\n");
  return (
    <Card>
      <CardHeader>
        <CardTitle>Как подключиться</CardTitle>
        <CardDescription>
          Публичный API живёт под <code>/api/v1</code>. Токен передаётся в заголовке Authorization;
          лимит — 600 запросов в минуту на токен.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <pre className="overflow-x-auto rounded-lg bg-secondary p-3 text-xs">{example}</pre>
        <p className="text-sm text-muted-foreground">
          Типовой сценарий: выбрать опубликованную вакансию → пригласить кандидата (ссылка в
          ответе показывается один раз) → опрашивать статус интервью → забрать отчёт и
          ранжирование. Полное описание ручек, схем и ошибок — в документации.
        </p>
        <DocsLink />
      </CardContent>
    </Card>
  );
}

export default function IntegrationsPage() {
  const { can } = useAuth();
  return <>
    <PageHeader title="Интеграции" description="Подключите сервисы, с которыми работает команда." />
    <Tabs defaultValue="catalog">
      <TabsList className="mb-6"><TabsTrigger value="catalog">Каталог</TabsTrigger><TabsTrigger value="api">API и токены</TabsTrigger></TabsList>
      <TabsContent value="catalog">
        <div className="integrations-catalog">
          <article className="integration-card integration-hh">
            <img src="/brand/hh.ico" alt="hh.ru" className="integration-logo" />
            <h2>От отклика до интервью</h2><p>Приглашайте кандидатов из hh.ru и общайтесь в одном месте.</p>
            <ul><li>Импорт вакансий и откликов</li><li>Ссылка на интервью в чате hh.ru</li><li>История общения с кандидатом</li></ul>
            <Button asChild><Link href="/integrations/hh">Настроить hh.ru<ArrowRight size={17} /></Link></Button>
          </article>
          <article className="integration-card integration-huntflow">
            <img src="/brand/huntflow.svg" alt="Huntflow" className="integration-logo" />
            <h2>Результаты в вашей ATS</h2><p>Передавайте кандидатов и отчёты в рабочую воронку команды.</p>
            <ul><li>Связь с вакансиями в Huntflow</li><li>Кандидаты и результаты интервью</li><li>Ссылка на подробный отчёт</li></ul>
            <Button asChild variant="outline"><Link href="/integrations/huntflow">Настроить Huntflow<ArrowRight size={17} /></Link></Button>
          </article>
        </div>
        <div className="integration-journey"><h2>Три шага к подключению</h2><ol>
          <li><span>01</span><Mascot name="fox" /><div><strong>Подключите аккаунт</strong><p>Разрешите доступ к сервису.</p></div></li>
          <li><span>02</span><Mascot name="rabbit" /><div><strong>Свяжите вакансии</strong><p>Выберите вакансии для интервью.</p></div></li>
          <li><span>03</span><Mascot name="bear" /><div><strong>Пригласите кандидатов</strong><p>Отправьте ссылки на интервью.</p></div></li>
        </ol></div>
      </TabsContent>
      <TabsContent value="api" className="space-y-5">
        {can("api_tokens.manage") ? <ApiTokensCard /> : <p className="p-6 text-muted-foreground">Токенами управляет владелец организации.</p>}
        <QuickStartCard />
      </TabsContent>
    </Tabs>
  </>;
}
