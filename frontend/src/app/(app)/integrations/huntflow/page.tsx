"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Download, Link2, Loader2, Plug, Unlink } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
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
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import {
  CONNECTION_STATUS_LABELS,
  TOKEN_HINT,
  VACANCY_STATE_LABELS,
  huntflowApi,
  type HuntflowConnection,
  type HuntflowFunnelStatus,
  type HuntflowVacancy,
  type HuntflowVacancyLink,
} from "@/lib/api/huntflow";
import { VACANCY_STATUS_LABELS, vacanciesApi, type VacancyListItem } from "@/lib/api/vacancies";

const FIRST_STATUS = "first";

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

function statusVariant(status: HuntflowConnection["status"]): "default" | "secondary" | "destructive" {
  if (status === "active") return "default";
  if (status === "error") return "destructive";
  return "secondary";
}

function ConnectForm({
  connection,
  onChanged,
}: {
  connection: HuntflowConnection;
  onChanged: (next: HuntflowConnection) => void;
}) {
  const showError = useErrorToast();
  const { toast } = useToast();
  const [token, setToken] = useState("");
  const [pending, setPending] = useState<"token" | "demo" | null>(null);

  const connect = async (body: { token?: string; demo?: boolean }) => {
    setPending(body.demo ? "demo" : "token");
    try {
      const next = await huntflowApi.connect(body);
      onChanged(next);
      setToken("");
      toast({
        title:
          next.status === "active"
            ? `Huntflow подключён: ${next.account?.name ?? ""}`
            : next.status === "needs_account"
              ? "Токен принят — выберите аккаунт"
              : "Подключение не удалось",
        variant: next.status === "error" ? "destructive" : undefined,
      });
    } catch (error) {
      showError(error, "Не удалось подключить Huntflow");
    } finally {
      setPending(null);
    }
  };

  if (!connection.can_manage) {
    return (
      <p className="text-sm text-muted-foreground">
        Подключение настраивает владелец организации. Как только оно появится, здесь будут вакансии
        Huntflow и импорт соискателей.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor="huntflow-token">Персональный токен</Label>
        <Input
          id="huntflow-token"
          type="password"
          autoComplete="off"
          placeholder="Вставьте токен из Huntflow"
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <p className="text-xs text-muted-foreground">{TOKEN_HINT}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => connect({ token })} disabled={pending !== null || !token.trim()}>
          {pending === "token" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Plug className="mr-2 h-4 w-4" />
          )}
          Подключить
        </Button>
        {connection.demo_available ? (
          <Button variant="outline" onClick={() => connect({ demo: true })} disabled={pending !== null}>
            {pending === "demo" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Подключить демо
          </Button>
        ) : null}
      </div>
      {connection.demo_available ? (
        <p className="text-xs text-muted-foreground">
          Демо-режим работает без токена на встроенных фикстурах: аккаунт, три вакансии, воронка и
          соискатели. Подходит, чтобы посмотреть сценарий передачи кандидата.
        </p>
      ) : null}
    </div>
  );
}

function AccountPicker({
  connection,
  onChanged,
}: {
  connection: HuntflowConnection;
  onChanged: (next: HuntflowConnection) => void;
}) {
  const showError = useErrorToast();
  const [accountId, setAccountId] = useState<string>(
    connection.available_accounts[0] ? String(connection.available_accounts[0].id) : "",
  );
  const [pending, setPending] = useState(false);

  const choose = async () => {
    setPending(true);
    try {
      onChanged(await huntflowApi.selectAccount(Number(accountId)));
    } catch (error) {
      showError(error, "Не удалось выбрать аккаунт");
    } finally {
      setPending(false);
    }
  };

  if (connection.available_accounts.length === 0) {
    return (
      <p className="text-sm text-destructive">
        Не удалось получить список аккаунтов — проверьте токен или подключите заново.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="space-y-2">
        <Label>Аккаунт Huntflow</Label>
        <Select value={accountId} onValueChange={setAccountId}>
          <SelectTrigger className="w-[260px]">
            <SelectValue placeholder="Выберите аккаунт" />
          </SelectTrigger>
          <SelectContent>
            {connection.available_accounts.map((account) => (
              <SelectItem key={account.id} value={String(account.id)}>
                {account.name}
                {account.nick ? ` (${account.nick})` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button onClick={choose} disabled={pending || !accountId || !connection.can_manage}>
        {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Выбрать
      </Button>
    </div>
  );
}

function DisconnectButton({ onDone }: { onDone: () => void }) {
  const showError = useErrorToast();
  const [pending, setPending] = useState(false);
  const disconnect = async () => {
    setPending(true);
    try {
      await huntflowApi.disconnect();
      onDone();
    } catch (error) {
      showError(error, "Не удалось отключить Huntflow");
    } finally {
      setPending(false);
    }
  };
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="outline" disabled={pending}>
          Отключить
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Отключить Huntflow?</AlertDialogTitle>
          <AlertDialogDescription>
            Токен будет удалён, привязки вакансий и история передач — тоже. Кандидаты и уже
            переданные в Huntflow соискатели останутся на месте.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Отмена</AlertDialogCancel>
          <AlertDialogAction onClick={disconnect}>Отключить</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function ConnectionCard({
  connection,
  onChanged,
}: {
  connection: HuntflowConnection;
  onChanged: (next: HuntflowConnection | null) => void;
}) {
  const showForm = !connection.connected || connection.status === "error";
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>Подключение</CardTitle>
          <CardDescription>
            Персональный токен Huntflow даёт доступ к вакансиям и соискателям вашего аккаунта.
          </CardDescription>
        </div>
        {connection.connected && connection.status ? (
          <Badge variant={statusVariant(connection.status)}>
            {CONNECTION_STATUS_LABELS[connection.status]}
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {connection.connected ? (
          <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
            <dt className="text-muted-foreground">Аккаунт</dt>
            <dd>{connection.account?.name ?? "не выбран"}</dd>
            <dt className="text-muted-foreground">Токен</dt>
            <dd>
              {connection.owner_name ?? "—"}
              {connection.owner_email ? ` · ${connection.owner_email}` : ""}
            </dd>
            <dt className="text-muted-foreground">Подключил</dt>
            <dd>
              {connection.connected_by_email ?? "—"} · {formatDate(connection.connected_at)}
            </dd>
            <dt className="text-muted-foreground">Привязано вакансий</dt>
            <dd>{connection.linked_vacancies}</dd>
          </dl>
        ) : null}
        {connection.last_error ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {connection.last_error}
          </p>
        ) : null}
        {connection.status === "needs_account" ? (
          <AccountPicker connection={connection} onChanged={onChanged} />
        ) : null}
        {showForm ? <ConnectForm connection={connection} onChanged={onChanged} /> : null}
        {connection.connected && connection.can_manage ? (
          <div className="flex justify-end">
            <DisconnectButton onDone={() => onChanged(null)} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function LinkRow({
  link,
  canLink,
  canImport,
  onChanged,
}: {
  link: HuntflowVacancyLink;
  canLink: boolean;
  canImport: boolean;
  onChanged: () => void;
}) {
  const showError = useErrorToast();
  const { toast } = useToast();
  const [pending, setPending] = useState<"import" | "unlink" | null>(null);

  const importApplicants = async () => {
    setPending("import");
    try {
      const result = await huntflowApi.importApplicants(link.vacancy_id);
      toast({
        title: `Импорт завершён: новых ${result.created}, уже были ${result.existing}, пропущено ${result.skipped}`,
      });
      onChanged();
    } catch (error) {
      showError(error, "Не удалось импортировать соискателей");
    } finally {
      setPending(null);
    }
  };

  const unlink = async () => {
    setPending("unlink");
    try {
      await huntflowApi.unlink(link.vacancy_id);
      onChanged();
    } catch (error) {
      showError(error, "Не удалось отвязать вакансию");
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-2 text-sm">
      <div className="min-w-0">
        <Link href={`/vacancies/${link.vacancy_id}`} className="font-medium hover:underline">
          {link.vacancy_title}
        </Link>
        <div className="text-xs text-muted-foreground">
          статус при передаче: {link.status_name ?? "первый в воронке"}
          {link.last_imported_at ? ` · импорт ${formatDate(link.last_imported_at)}` : ""}
        </div>
      </div>
      <div className="flex items-center gap-1">
        {canImport ? (
          <Button variant="ghost" size="sm" onClick={importApplicants} disabled={pending !== null}>
            {pending === "import" ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-1 h-4 w-4" />
            )}
            Импортировать соискателей
          </Button>
        ) : null}
        {canLink ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={unlink}
            disabled={pending !== null}
            aria-label="Отвязать"
            title="Отвязать"
          >
            {pending === "unlink" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Unlink className="h-4 w-4" />}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function AddLink({
  vacancy,
  statuses,
  localVacancies,
  onChanged,
}: {
  vacancy: HuntflowVacancy;
  statuses: HuntflowFunnelStatus[];
  localVacancies: VacancyListItem[];
  onChanged: () => void;
}) {
  const showError = useErrorToast();
  const [localId, setLocalId] = useState("");
  const [statusId, setStatusId] = useState(FIRST_STATUS);
  const [pending, setPending] = useState(false);

  const link = async () => {
    setPending(true);
    try {
      await huntflowApi.link(localId, {
        huntflow_vacancy_id: vacancy.id,
        status_id: statusId === FIRST_STATUS ? null : Number(statusId),
      });
      setLocalId("");
      onChanged();
    } catch (error) {
      showError(error, "Не удалось привязать вакансию");
    } finally {
      setPending(false);
    }
  };

  if (localVacancies.length === 0) {
    return <p className="text-xs text-muted-foreground">Все локальные вакансии уже привязаны.</p>;
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={localId} onValueChange={setLocalId}>
        <SelectTrigger className="w-[220px]" aria-label="Локальная вакансия">
          <SelectValue placeholder="Локальная вакансия" />
        </SelectTrigger>
        <SelectContent>
          {localVacancies.map((item) => (
            <SelectItem key={item.id} value={item.id}>
              {item.title}
              <span className="ml-1 text-xs text-muted-foreground">
                · {VACANCY_STATUS_LABELS[item.status]}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={statusId} onValueChange={setStatusId}>
        <SelectTrigger className="w-[200px]" aria-label="Статус при передаче">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={FIRST_STATUS}>Первый статус воронки</SelectItem>
          {statuses.map((status) => (
            <SelectItem key={status.id} value={String(status.id)}>
              {status.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button size="sm" variant="outline" onClick={link} disabled={pending || !localId}>
        {pending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Link2 className="mr-1 h-4 w-4" />}
        Привязать
      </Button>
    </div>
  );
}

function VacanciesCard({ onLinksChanged }: { onLinksChanged: () => void }) {
  const { can } = useAuth();
  const showError = useErrorToast();
  const [items, setItems] = useState<HuntflowVacancy[] | null>(null);
  const [statuses, setStatuses] = useState<HuntflowFunnelStatus[]>([]);
  const [localVacancies, setLocalVacancies] = useState<VacancyListItem[]>([]);
  const canLink = can("vacancy.write");
  const canImport = can("candidate.write");

  const load = useCallback(async () => {
    try {
      const [remote, local] = await Promise.all([huntflowApi.vacancies(), vacanciesApi.list()]);
      setItems(remote.items);
      setStatuses(remote.statuses);
      setLocalVacancies(local.filter((item) => item.status !== "archived"));
    } catch (error) {
      setItems([]);
      showError(error, "Не удалось загрузить вакансии Huntflow");
    }
  }, [showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const linkedLocalIds = useMemo(
    () => new Set((items ?? []).flatMap((item) => item.links.map((link) => link.vacancy_id))),
    [items],
  );
  const freeLocal = useMemo(
    () => localVacancies.filter((item) => !linkedLocalIds.has(item.id)),
    [localVacancies, linkedLocalIds],
  );

  const changed = () => {
    void load();
    onLinksChanged();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Вакансии Huntflow</CardTitle>
        <CardDescription>
          Привяжите вакансию Huntflow к локальной: кандидаты этой вакансии передаются в неё с выбранным
          статусом, а соискателей можно импортировать в кандидаты.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        {items === null ? (
          <div className="p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : items.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">В аккаунте Huntflow нет вакансий.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[280px]">Вакансия Huntflow</TableHead>
                <TableHead>Привязка к локальным вакансиям</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((vacancy) => (
                <TableRow key={vacancy.id}>
                  <TableCell className="align-top">
                    <div className="font-medium">{vacancy.position}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                      <span>#{vacancy.id}</span>
                      {vacancy.state ? (
                        <Badge variant="outline" className="text-[11px]">
                          {VACANCY_STATE_LABELS[vacancy.state] ?? vacancy.state}
                        </Badge>
                      ) : null}
                      {vacancy.company ? <span>· {vacancy.company}</span> : null}
                    </div>
                  </TableCell>
                  <TableCell className="space-y-2 align-top">
                    {vacancy.links.map((link) => (
                      <LinkRow
                        key={link.vacancy_id}
                        link={link}
                        canLink={canLink}
                        canImport={canImport}
                        onChanged={changed}
                      />
                    ))}
                    {vacancy.links.length === 0 && !canLink ? (
                      <p className="text-xs text-muted-foreground">Не привязана.</p>
                    ) : null}
                    {canLink ? (
                      <AddLink
                        vacancy={vacancy}
                        statuses={statuses}
                        localVacancies={freeLocal}
                        onChanged={changed}
                      />
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

export default function HuntflowIntegrationPage() {
  const showError = useErrorToast();
  const [connection, setConnection] = useState<HuntflowConnection | null | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      setConnection(await huntflowApi.status());
    } catch (error) {
      setConnection(null);
      showError(error, "Не удалось загрузить состояние интеграции");
    }
  }, [showError]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Huntflow"
        description="Передача кандидата со ссылкой на отчёт в Huntflow и импорт соискателей из привязанных вакансий."
        actions={
          <>
            {connection?.mode === "fake" ? <Badge variant="secondary">Демо-режим</Badge> : null}
            <Button asChild variant="outline">
              <Link href="/integrations">
                <ArrowLeft className="mr-2 h-4 w-4" />
                Интеграции
              </Link>
            </Button>
          </>
        }
      />
      {connection === undefined ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : connection === null ? (
        <p className="text-sm text-muted-foreground">
          Интеграции доступны владельцу и рекрутерам организации.
        </p>
      ) : (
        <div className="space-y-6">
          <ConnectionCard
            connection={connection}
            onChanged={(next) => {
              if (next) setConnection(next);
              else void load();
            }}
          />
          {connection.connected && connection.status === "active" ? (
            <VacanciesCard onLinksChanged={() => void load()} />
          ) : null}
        </div>
      )}
    </>
  );
}
