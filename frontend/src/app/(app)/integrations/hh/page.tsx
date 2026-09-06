"use client";

import { RowsSkeleton, Skeleton } from "@/components/ui/skeleton";

import Link from "@/lib/router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ExternalLink,
  KeyRound,
  MessageSquareText,
  Plug,
  RefreshCw,
  Settings2,
  Unplug,
} from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { CopyField } from "@/components/candidates/invite-dialog";
import { HhDialogStateBadge, HhDialogThread } from "@/components/integrations/hh-dialog";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import {
  HH_PLACEHOLDER_HINTS,
  hhApi,
  type HhDialogSettings,
  type HhNegotiation,
  type HhStatus,
  type HhVacancy,
  type HhVacancyLink,
} from "@/lib/api/hh";
import { VACANCY_STATUS_LABELS, vacanciesApi, type VacancyListItem, type VacancyStatus } from "@/lib/api/vacancies";

const CONNECTION_STATUS_LABELS = {
  connected: "Подключено",
  error: "Ошибка",
  disconnected: "Отключено",
} as const;

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("ru-RU");
}

/** Та же подстановка, что на сервере: неизвестные плейсхолдеры остаются как есть. */
function renderTemplate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
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

// ------------------------------------------------------------ подключение

/*
 * Готовый токен: у работодателя уже есть рабочая авторизация hh.ru в другом
 * приложении, а повторный OAuth выдал бы новый токен и сломал старую. Токен
 * вставляется один раз, уходит по HTTPS, хранится шифрованным и не обновляется
 * сервисом — refresh инвалидировал бы пару у приложения-источника.
 */
function TokenConnectForm({ onChange, compact = false }: { onChange: (next: HhStatus) => void; compact?: boolean }) {
  const { toast } = useToast();
  const showError = useErrorToast();
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [expires, setExpires] = useState("");
  const [pending, setPending] = useState(false);

  const submit = async () => {
    setPending(true);
    try {
      const expiresAt = expires ? new Date(`${expires}T23:59:59`).toISOString() : null;
      onChange(await hhApi.connectToken({ access_token: token.trim(), expires_at: expiresAt }));
      setToken("");
      setExpires("");
      setOpen(false);
      toast({ title: "HH.ru подключён готовым токеном" });
    } catch (error) {
      showError(error, "HH не принял токен");
    } finally {
      setPending(false);
    }
  };

  if (!open) {
    return (
      <Button variant={compact ? "ghost" : "outline"} size="sm" onClick={() => setOpen(true)}>
        <KeyRound className="mr-2 h-4 w-4" />
        {compact ? "Вставить новый токен" : "У меня уже есть токен из другого приложения"}
      </Button>
    );
  }
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div>
        <p className="font-medium">Подключить готовым токеном</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Если авторизация hh.ru уже выполнена в другом приложении того же работодателя, вставьте его
          access_token: повторный вход через hh не понадобится, и токен источника останется рабочим.
          Сервис не обновляет такой токен сам — по истечении срока вставьте новый.
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor="hh-token">access_token</Label>
        <Textarea
          id="hh-token"
          rows={3}
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Вставьте токен целиком"
          autoComplete="off"
          spellCheck={false}
          className="font-mono text-xs"
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="hh-token-expires">Действует до (необязательно)</Label>
        <Input
          id="hh-token-expires"
          type="date"
          value={expires}
          onChange={(event) => setExpires(event.target.value)}
          className="max-w-[220px]"
        />
        <p className="text-xs text-muted-foreground">Если не знаете — оставьте пустым: hh выдаёт токен на 14 дней.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={submit} disabled={pending || token.trim().length < 16}>
          <KeyRound className="mr-2 h-4 w-4" />
          Подключить
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
          Отмена
        </Button>
      </div>
    </div>
  );
}

function ConnectionCard({
  status,
  onChange,
  onSynced,
}: {
  status: HhStatus;
  onChange: (next: HhStatus) => void;
  onSynced: () => void;
}) {
  const { can } = useAuth();
  const { toast } = useToast();
  const showError = useErrorToast();
  const [pending, setPending] = useState<"connect" | "disconnect" | "sync" | null>(null);
  const manages = can("integrations.manage");
  const operates = can("integrations.operate");
  const demo = status.mode === "fake";
  const connection = status.connection;

  const connect = async () => {
    setPending("connect");
    try {
      if (demo) {
        onChange(await hhApi.connectDemo());
        toast({ title: "Демо-аккаунт HH подключён" });
      } else {
        const { url } = await hhApi.oauthStart();
        window.location.href = url;
      }
    } catch (error) {
      showError(error, "Не удалось начать подключение");
    } finally {
      setPending(null);
    }
  };

  const disconnect = async () => {
    setPending("disconnect");
    try {
      onChange(await hhApi.disconnect());
      toast({ title: "HH.ru отключён" });
    } catch (error) {
      showError(error, "Не удалось отключить");
    } finally {
      setPending(null);
    }
  };

  const sync = async () => {
    setPending("sync");
    try {
      await hhApi.sync();
      toast({
        title: "Синхронизация поставлена в очередь",
        description: "Воркер обработает отклики в течение минуты — обновите страницу.",
      });
      onSynced();
    } catch (error) {
      showError(error, "Не удалось запустить синхронизацию");
    } finally {
      setPending(null);
    }
  };

  return (
    <Card className="integration-connection">
      <header className="leon-card-header">
        <div>
          <CardTitle className="flex flex-wrap items-center gap-2">
            Подключение
            {demo ? <Badge variant="outline">Демо-режим</Badge> : null}
          </CardTitle>
          <CardDescription>
            {demo
              ? "Посмотрите вакансии и отклики на демонстрационном аккаунте."
              : "Войдите в аккаунт работодателя на hh.ru, чтобы получать вакансии и отклики."}
          </CardDescription>
        </div>
        {connection ? (
          <Badge variant={connection.status === "connected" ? "default" : "destructive"}>
            {CONNECTION_STATUS_LABELS[connection.status]}
          </Badge>
        ) : null}
      </header>
      <div className="leon-card-content space-y-4">
        {connection ? (
          <>
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Работодатель</dt>
                <dd className="font-medium">
                  {connection.employer_name || "—"}
                  {connection.employer_id ? (
                    <span className="ml-2 font-mono text-xs text-muted-foreground">#{connection.employer_id}</span>
                  ) : null}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Последняя синхронизация</dt>
                <dd>{formatDateTime(connection.last_synced_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Подключено</dt>
                <dd>{formatDateTime(connection.connected_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Автосинхронизация</dt>
                <dd>каждые {status.sync_interval_minutes} мин</dd>
              </div>
            </dl>
            {connection.mode === "real" && connection.token_refreshable === false ? (
              <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
                Подключено готовым токеном без refresh_token: сервис не обновляет его сам, чтобы не
                сломать авторизацию в приложении-источнике. Действует до{" "}
                <span className="font-medium text-foreground">{formatDateTime(connection.expires_at ?? null)}</span>;
                когда истечёт — вставьте новый токен ниже.
              </p>
            ) : null}
            {connection.last_error ? (
              <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                {connection.last_error}
              </p>
            ) : null}
            {connection.webhook_url ? (
              <div className="space-y-1">
                <Label>Адрес вебхука для HH</Label>
                <CopyField value={connection.webhook_url} />
                <p className="text-xs text-muted-foreground">
                  Укажите его в настройках уведомлений приложения HH: любое событие — сигнал перечитать отклики.
                  Адрес содержит секрет и виден только владельцу.
                </p>
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {operates ? (
                <Button onClick={sync} disabled={pending !== null}>
                  {pending === "sync" ? (
                    <Skeleton className="mr-2 h-4 w-4 rounded-md" />
                  ) : (
                    <RefreshCw className="mr-2 h-4 w-4" />
                  )}
                  Синхронизировать сейчас
                </Button>
              ) : null}
              {manages ? (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="outline" disabled={pending !== null}>
                      <Unplug className="mr-2 h-4 w-4" />
                      Отключить
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Отключить HH.ru?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Токены будут удалены, синхронизация остановится. Привязки вакансий и история диалогов
                        останутся в карточках кандидатов.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Отмена</AlertDialogCancel>
                      <AlertDialogAction onClick={disconnect}>Отключить</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              ) : null}
            </div>
            {connection.mode === "real" && manages ? <TokenConnectForm onChange={onChange} compact /> : null}
          </>
        ) : manages ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={connect} disabled={pending !== null}>
                {pending === "connect" ? (
                  <Skeleton className="mr-2 h-4 w-4 rounded-md" />
                ) : (
                  <Plug className="mr-2 h-4 w-4" />
                )}
                {demo ? "Подключить демо-аккаунт" : "Подключить HH.ru"}
              </Button>
              <p className="text-sm text-muted-foreground">
                {demo
                  ? "Появятся три вакансии и пять откликов со сценарными ответами кандидатов."
                  : "Откроется страница авторизации hh.ru; после согласия вы вернётесь сюда."}
              </p>
            </div>
            {!demo ? <TokenConnectForm onChange={onChange} /> : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Подключение и отключение HH.ru доступны владельцу организации.
          </p>
        )}
      </div>
    </Card>
  );
}

// -------------------------------------------------------------- вакансии

function LinkToExisting({
  vacancy,
  locals,
  onLinked,
}: {
  vacancy: HhVacancy;
  locals: VacancyListItem[];
  onLinked: (link: HhVacancyLink) => void;
}) {
  const showError = useErrorToast();
  const [target, setTarget] = useState<string>("");
  const [pending, setPending] = useState(false);

  const submit = async () => {
    if (!target) return;
    setPending(true);
    try {
      onLinked(await hhApi.linkVacancy(vacancy.id, target));
    } catch (error) {
      showError(error, "Не удалось привязать вакансию");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex items-center gap-1">
      <Select value={target} onValueChange={setTarget}>
        <SelectTrigger className="h-8 w-[180px] text-xs">
          <SelectValue placeholder="Привязать к…" />
        </SelectTrigger>
        <SelectContent>
          {locals.map((local) => (
            <SelectItem key={local.id} value={local.id}>
              {local.title}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button size="sm" variant="outline" disabled={!target || pending} onClick={submit}>
        {pending ? <Skeleton className="h-4 w-4 rounded-md" /> : "ОК"}
      </Button>
    </div>
  );
}

function VacanciesCard({
  vacancies,
  locals,
  onChanged,
  onEditDialog,
}: {
  vacancies: HhVacancy[] | null;
  locals: VacancyListItem[];
  onChanged: () => void;
  onEditDialog: (link: HhVacancyLink) => void;
}) {
  const { can } = useAuth();
  const { toast } = useToast();
  const showError = useErrorToast();
  const operates = can("integrations.operate");
  const [importing, setImporting] = useState<string | null>(null);

  const importVacancy = async (vacancy: HhVacancy) => {
    setImporting(vacancy.id);
    try {
      const link = await hhApi.importVacancy(vacancy.id);
      toast({
        title: "Вакансия импортирована как черновик",
        description: "Добавьте вопросы и опубликуйте её — тогда бот начнёт отправлять ссылки.",
      });
      onChanged();
      onEditDialog(link);
    } catch (error) {
      showError(error, "Не удалось импортировать вакансию");
    } finally {
      setImporting(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Вакансии на HH</CardTitle>
        <CardDescription>
          Активные вакансии работодателя. Импорт создаёт локальный черновик с описанием, требованиями и
          навыками; привязка соединяет отклики с уже настроенной вакансией.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        {vacancies === null ? (
          <div className="p-6">
            <RowsSkeleton />
          </div>
        ) : vacancies.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">У работодателя нет активных вакансий.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Вакансия</TableHead>
                <TableHead>Навыки</TableHead>
                <TableHead>Локальная вакансия</TableHead>
                <TableHead className="text-right">Действия</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {vacancies.map((vacancy) => (
                <TableRow key={vacancy.id}>
                  <TableCell>
                    <div className="font-medium">
                      {vacancy.url ? (
                        <a href={vacancy.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline">
                          {vacancy.name}
                          <ExternalLink className="h-3 w-3 text-muted-foreground" />
                        </a>
                      ) : (
                        vacancy.name
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {[vacancy.area, vacancy.salary].filter(Boolean).join(" · ") || "—"}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex max-w-[260px] flex-wrap gap-1">
                      {vacancy.key_skills.slice(0, 5).map((skill) => (
                        <Badge key={skill} variant="outline" className="text-[11px]">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    {vacancy.link ? (
                      <div className="space-y-1">
                        <Link href={`/vacancies/${vacancy.link.vacancy_id}`} className="font-medium hover:underline">
                          {vacancy.link.vacancy_title}
                        </Link>
                        <div className="flex flex-wrap items-center gap-1 text-xs">
                          <Badge variant={vacancy.link.vacancy_status === "published" ? "default" : "secondary"}>
                            {VACANCY_STATUS_LABELS[vacancy.link.vacancy_status as VacancyStatus] ?? vacancy.link.vacancy_status}
                          </Badge>
                          <span className="text-muted-foreground">
                            диалог {vacancy.link.dialog_enabled ? "включён" : "выключен"} · откликов:{" "}
                            {vacancy.link.negotiation_count}
                          </span>
                        </div>
                      </div>
                    ) : (
                      <span className="text-sm text-muted-foreground">не привязана</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {operates ? (
                      vacancy.link ? (
                        <Button size="sm" variant="ghost" onClick={() => onEditDialog(vacancy.link as HhVacancyLink)}>
                          <Settings2 className="mr-1 h-4 w-4" />
                          Диалог
                        </Button>
                      ) : (
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={importing === vacancy.id}
                            onClick={() => importVacancy(vacancy)}
                          >
                            {importing === vacancy.id ? <Skeleton className="mr-1 h-4 w-4 rounded-md" /> : null}
                            Импортировать
                          </Button>
                          {locals.length > 0 ? (
                            <LinkToExisting vacancy={vacancy} locals={locals} onLinked={() => onChanged()} />
                          ) : null}
                        </div>
                      )
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

// ---------------------------------------------------------- редактор диалога

const STEPS: { key: keyof Pick<HhDialogSettings, "greeting" | "clarify" | "link">; title: string; hint: string }[] = [
  { key: "greeting", title: "Шаг 1 — приветствие", hint: "Отправляется сразу после отклика: спасибо и вопрос об удобном дне." },
  { key: "clarify", title: "Шаг 2 — уточнение", hint: "Если день не удалось разобрать. После второй неудачи отклик уходит рекрутеру." },
  { key: "link", title: "Шаг 3 — ссылка", hint: "Когда день выбран: ссылка на интервью действует до выбранного дня плюс один." },
];

function DialogEditor({
  link,
  onClose,
  onSaved,
}: {
  link: HhVacancyLink | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const showError = useErrorToast();
  const [form, setForm] = useState<HhDialogSettings | null>(null);
  const [placeholders, setPlaceholders] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!link) {
      setForm(null);
      return;
    }
    let cancelled = false;
    hhApi
      .dialog(link.id)
      .then((dialog) => {
        if (cancelled) return;
        setForm({
          enabled: dialog.enabled,
          max_days: dialog.max_days,
          greeting: dialog.greeting,
          clarify: dialog.clarify,
          link: dialog.link,
        });
        setPlaceholders(dialog.placeholders);
      })
      .catch((error) => showError(error, "Не удалось загрузить настройку диалога"));
    return () => {
      cancelled = true;
    };
  }, [link, showError]);

  const sample = useMemo(() => {
    const expires = new Date();
    expires.setDate(expires.getDate() + 3);
    return {
      candidate_name: "Анна",
      vacancy_title: link?.vacancy_title || link?.hh_title || "Вакансия",
      days: form?.max_days ?? 7,
      link: `${typeof window !== "undefined" ? window.location.origin : ""}/i/<токен>`,
      date: `${expires.getDate()} ${MONTHS[expires.getMonth()]}`,
    };
  }, [link, form?.max_days]);

  const save = async () => {
    if (!link || !form) return;
    setSaving(true);
    try {
      await hhApi.updateDialog(link.id, form);
      toast({ title: "Настройки диалога сохранены" });
      onSaved();
      onClose();
    } catch (error) {
      showError(error, "Не удалось сохранить диалог");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={link !== null} onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Диалог с откликнувшимися</DialogTitle>
          <DialogDescription>
            {link ? (
              <>
                «{link.hh_title}» → <span className="font-medium text-foreground">{link.vacancy_title}</span>.
                Плейсхолдеры подставляются при отправке:{" "}
                {placeholders.map((name) => (
                  <code key={name} className="mr-1 rounded bg-secondary px-1 py-0.5 text-xs" title={HH_PLACEHOLDER_HINTS[name]}>
                    {`{${name}}`}
                  </code>
                ))}
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>
        {form === null ? (
          <RowsSkeleton />
        ) : (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-2 text-sm">
                <Switch aria-label="Диалог с откликнувшимися" checked={form.enabled} onCheckedChange={(enabled) => setForm({ ...form, enabled })} />
                Диалог включён
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Label htmlFor="hh-max-days">Окно, дней</Label>
                <Input
                  id="hh-max-days"
                  type="number"
                  min={1}
                  max={60}
                  className="w-20"
                  value={form.max_days}
                  onChange={(event) =>
                    setForm({ ...form, max_days: Math.max(1, Math.min(60, Number(event.target.value) || 1)) })
                  }
                />
              </div>
            </div>
            {STEPS.map((step) => (
              <div key={step.key} className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor={`hh-${step.key}`}>{step.title}</Label>
                  <Textarea
                    id={`hh-${step.key}`}
                    rows={5}
                    value={form[step.key]}
                    onChange={(event) => setForm({ ...form, [step.key]: event.target.value })}
                  />
                  <p className="text-xs text-muted-foreground">{step.hint}</p>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-muted-foreground">Превью</Label>
                  <div className="rounded-2xl rounded-tl-sm bg-secondary px-3.5 py-2 text-sm whitespace-pre-wrap break-words">
                    {renderTemplate(form[step.key], sample) || <span className="text-muted-foreground">пусто</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={save} disabled={saving || form === null}>
            {saving ? <Skeleton className="mr-2 h-4 w-4 rounded-md" /> : null}
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- отклики

function NegotiationsCard({
  items,
  onChanged,
}: {
  items: HhNegotiation[] | null;
  onChanged: (updated?: HhNegotiation) => void;
}) {
  const { can } = useAuth();
  const { toast } = useToast();
  const showError = useErrorToast();
  const operates = can("integrations.operate");
  const [opened, setOpened] = useState<HhNegotiation | null>(null);
  const [taking, setTaking] = useState<string | null>(null);

  const takeOver = async (item: HhNegotiation) => {
    setTaking(item.id);
    try {
      const updated = await hhApi.takeOver(item.id);
      toast({ title: "Ссылка на интервью отправлена в чат HH" });
      onChanged(updated);
    } catch (error) {
      showError(error, "Не удалось отправить ссылку");
    } finally {
      setTaking(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Отклики</CardTitle>
        <CardDescription>
          Кандидаты создаются из резюме автоматически. Бот здоровается, спрашивает удобный день и отправляет
          ссылку; когда не справился — отклик ждёт рекрутера.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        {items === null ? (
          <div className="p-6">
            <RowsSkeleton />
          </div>
        ) : items.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">
            Откликов пока нет. Привяжите вакансию и запустите синхронизацию.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Кандидат</TableHead>
                <TableHead>Вакансия</TableHead>
                <TableHead>Диалог</TableHead>
                <TableHead>Выбранный день</TableHead>
                <TableHead>Обновлено</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <Link href={`/candidates/${item.candidate_id}`} className="font-medium hover:underline">
                      {item.candidate_name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{item.candidate_email}</div>
                  </TableCell>
                  <TableCell>
                    <Link href={`/vacancies/${item.vacancy_id}`} className="hover:underline">
                      {item.vacancy_title}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <HhDialogStateBadge state={item.state} />
                      {item.last_error ? (
                        <span className="max-w-[220px] truncate text-xs text-destructive" title={item.last_error}>
                          {item.last_error}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm">{formatDate(item.chosen_date)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{formatDateTime(item.last_synced_at)}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setOpened(item)}>
                        <MessageSquareText className="mr-1 h-4 w-4" />
                        {item.messages.length}
                      </Button>
                      {operates && item.state === "needs_recruiter" ? (
                        <Button size="sm" variant="outline" disabled={taking === item.id} onClick={() => takeOver(item)}>
                          {taking === item.id ? <Skeleton className="mr-1 h-4 w-4 rounded-md" /> : null}
                          Взять в работу
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <Dialog open={opened !== null} onOpenChange={(open) => (!open ? setOpened(null) : null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          {opened ? (
            <>
              <DialogHeader>
                <DialogTitle>{opened.candidate_name}</DialogTitle>
                <DialogDescription>
                  {opened.vacancy_title} · <HhDialogStateBadge state={opened.state} />
                </DialogDescription>
              </DialogHeader>
              <HhDialogThread messages={opened.messages} />
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </Card>
  );
}

// ----------------------------------------------------------------- страница

export default function HhIntegrationPage() {
  const { toast } = useToast();
  const showError = useErrorToast();
  const [status, setStatus] = useState<HhStatus | null>(null);
  const [vacancies, setVacancies] = useState<HhVacancy[] | null>(null);
  const [locals, setLocals] = useState<VacancyListItem[]>([]);
  const [negotiations, setNegotiations] = useState<HhNegotiation[] | null>(null);
  const [editing, setEditing] = useState<HhVacancyLink | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await hhApi.status());
    } catch (error) {
      showError(error, "Не удалось загрузить состояние интеграции");
    }
  }, [showError]);

  const loadData = useCallback(async () => {
    try {
      const [hh, local, items] = await Promise.all([hhApi.vacancies(), vacanciesApi.list(), hhApi.negotiations()]);
      setVacancies(hh);
      setLocals(local.filter((v) => v.status !== "archived"));
      setNegotiations(items);
    } catch (error) {
      showError(error, "Не удалось загрузить данные HH");
    }
  }, [showError]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    if (status?.connection) void loadData();
    else {
      setVacancies(null);
      setNegotiations(null);
    }
  }, [status?.connection, loadData]);

  // Возврат из OAuth: ?status=connected|error (без useSearchParams — страница статична).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const result = params.get("status");
    if (!result) return;
    if (result === "connected") toast({ title: "HH.ru подключён" });
    else {
      const reason = params.get("reason");
      toast({
        variant: "destructive",
        title: "Подключить HH.ru не удалось",
        description:
          reason === "state"
            ? "Ссылка авторизации устарела — попробуйте ещё раз."
            : reason === "denied"
              ? "Доступ не был предоставлен."
              : "HH ответил ошибкой. Проверьте ключи приложения и адрес возврата.",
      });
    }
    window.history.replaceState(null, "", window.location.pathname);
  }, [toast]);

  return (
    <section className="integration-detail">
      <Link href="/integrations" className="integration-back">
        <ArrowLeft className="h-4 w-4" />
        Интеграции
      </Link>
      <PageHeader
        title="hh.ru" icon={<img src="/brand/hh.ico" alt="" className="integration-logo" />}
        description="Вакансии, отклики и общение с кандидатами."
      />
      {status === null ? (
        <RowsSkeleton />
      ) : (
        <div className="space-y-6">
          <ConnectionCard status={status} onChange={setStatus} onSynced={() => void loadData()} />
          {status.connection ? (
            <>
              <VacanciesCard
                vacancies={vacancies}
                locals={locals}
                onChanged={() => void loadData()}
                onEditDialog={setEditing}
              />
              <NegotiationsCard
                items={negotiations}
                onChanged={(updated) => {
                  if (updated) {
                    setNegotiations((current) => current?.map((n) => (n.id === updated.id ? updated : n)) ?? null);
                  } else void loadData();
                }}
              />
            </>
          ) : null}
        </div>
      )}
      <DialogEditor link={editing} onClose={() => setEditing(null)} onSaved={() => void loadData()} />
    </section>
  );
}
