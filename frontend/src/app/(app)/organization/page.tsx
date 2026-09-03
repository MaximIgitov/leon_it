"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Link2, Loader2, Plus, ShieldOff, UserCheck } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { PageHeader } from "@/components/layout/page-header";
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
import { useToast } from "@/hooks/use-toast";
import { accountsApi, type Invite, type Member, type Role } from "@/lib/api/accounts";
import { ApiError } from "@/lib/api/client";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, roleLabel } from "@/lib/roles";

const INVITE_STATUS_LABELS: Record<Invite["status"], string> = {
  active: "Действует",
  expired: "Истекла",
  revoked: "Отозвана",
  exhausted: "Использована",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function useErrorToast() {
  const { toast } = useToast();
  return useCallback(
    (error: unknown, fallback: string) => {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : fallback,
      });
    },
    [toast],
  );
}

function OrganizationCard() {
  const { me, refresh } = useAuth();
  const { toast } = useToast();
  const showError = useErrorToast();
  const [name, setName] = useState(me?.organization.name ?? "");
  const [retention, setRetention] = useState(String(me?.organization.retention_days ?? 180));
  const [pending, setPending] = useState(false);

  const save = async () => {
    setPending(true);
    try {
      await accountsApi.updateOrganization({ name, retention_days: Number(retention) });
      await refresh();
      toast({ title: "Настройки организации сохранены" });
    } catch (error) {
      showError(error, "Не удалось сохранить");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Организация</CardTitle>
        <CardDescription>
          Название видят кандидаты на странице интервью. Срок хранения — через сколько дней
          видео и аудио ответов удаляются автоматически.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-[1fr_180px_auto] sm:items-end">
        <div className="space-y-2">
          <Label htmlFor="org-name">Название</Label>
          <Input id="org-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="org-retention">Хранение медиа, дней</Label>
          <Input
            id="org-retention"
            type="number"
            min={7}
            max={3650}
            value={retention}
            onChange={(event) => setRetention(event.target.value)}
          />
        </div>
        <Button onClick={save} disabled={pending}>
          {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Сохранить
        </Button>
      </CardContent>
    </Card>
  );
}

function CreateInviteDialog({ onCreated }: { onCreated: (invite: Invite) => void }) {
  const showError = useErrorToast();
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<Role>("recruiter");
  const [email, setEmail] = useState("");
  const [days, setDays] = useState("7");
  const [multi, setMulti] = useState(false);
  const [pending, setPending] = useState(false);
  const [created, setCreated] = useState<Invite | null>(null);
  const [copied, setCopied] = useState(false);

  const reset = () => {
    setCreated(null);
    setCopied(false);
    setEmail("");
    setMulti(false);
    setDays("7");
  };

  const submit = async () => {
    setPending(true);
    try {
      const invite = await accountsApi.createInvite({
        role,
        email: email.trim() || undefined,
        expires_in_days: Number(days),
        max_uses: multi ? null : 1,
      });
      setCreated(invite);
      onCreated(invite);
    } catch (error) {
      showError(error, "Не удалось создать приглашение");
    } finally {
      setPending(false);
    }
  };

  const copy = async () => {
    if (!created?.url) return;
    try {
      await navigator.clipboard.writeText(created.url);
      setCopied(true);
    } catch {
      /* буфер недоступен — ссылка видна в поле, её можно выделить */
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
          Пригласить
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Приглашение по ссылке</DialogTitle>
          <DialogDescription>
            Ссылка даёт доступ с выбранной ролью. Её можно отозвать в любой момент.
          </DialogDescription>
        </DialogHeader>
        {created ? (
          <div className="space-y-3">
            <p className="text-sm">
              Ссылка создана. Она показывается один раз — скопируйте и отправьте участнику.
            </p>
            <div className="flex gap-2">
              <Input readOnly value={created.url ?? ""} onFocus={(event) => event.target.select()} />
              <Button variant="outline" onClick={copy} aria-label="Скопировать ссылку">
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Роль</Label>
              <Select value={role} onValueChange={(value) => setRole(value as Role)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(ROLE_LABELS) as Role[]).map((value) => (
                    <SelectItem key={value} value={value}>
                      {ROLE_LABELS[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">{ROLE_DESCRIPTIONS[role]}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-email">E-mail (необязательно)</Label>
              <Input
                id="invite-email"
                type="email"
                placeholder="Только этот адрес сможет принять приглашение"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="invite-days">Срок, дней</Label>
                <Input
                  id="invite-days"
                  type="number"
                  min={1}
                  max={30}
                  value={days}
                  onChange={(event) => setDays(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Использований</Label>
                <Select value={multi ? "many" : "one"} onValueChange={(v) => setMulti(v === "many")}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="one">Одно</SelectItem>
                    <SelectItem value="many">Без ограничения</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        )}
        <DialogFooter>
          {created ? (
            <Button onClick={() => setOpen(false)}>Готово</Button>
          ) : (
            <Button onClick={submit} disabled={pending}>
              {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Link2 className="mr-2 h-4 w-4" />}
              Создать ссылку
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MembersCard() {
  const { me } = useAuth();
  const showError = useErrorToast();
  const [members, setMembers] = useState<Member[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMembers(await accountsApi.members());
    } catch (error) {
      showError(error, "Не удалось загрузить участников");
    }
  }, [showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (id: string, action: () => Promise<Member>) => {
    setBusy(id);
    try {
      const updated = await action();
      setMembers((current) => current?.map((m) => (m.id === updated.id ? updated : m)) ?? null);
    } catch (error) {
      showError(error, "Действие не выполнено");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Участники</CardTitle>
        <CardDescription>
          Смена роли и отзыв доступа действуют сразу: активные сессии участника завершаются.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        {members === null ? (
          <div className="p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Участник</TableHead>
                <TableHead>Роль</TableHead>
                <TableHead>Последний вход</TableHead>
                <TableHead className="text-right">Доступ</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => {
                const self = member.user_id === me?.id;
                return (
                  <TableRow key={member.id} className={member.is_active ? "" : "opacity-60"}>
                    <TableCell>
                      <div className="font-medium">{member.full_name ?? member.email}</div>
                      <div className="text-xs text-muted-foreground">{member.email}</div>
                    </TableCell>
                    <TableCell>
                      <Select
                        value={member.role}
                        disabled={self || busy === member.id}
                        onValueChange={(value) =>
                          run(member.id, () =>
                            accountsApi.updateMember(member.id, { role: value as Role }),
                          )
                        }
                      >
                        <SelectTrigger className="w-[210px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(ROLE_LABELS) as Role[]).map((value) => (
                            <SelectItem key={value} value={value}>
                              {ROLE_LABELS[value]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(member.last_login_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {self ? (
                        <Badge variant="secondary">Это вы</Badge>
                      ) : member.is_active ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy === member.id}
                          onClick={() =>
                            run(member.id, () => accountsApi.deactivateMember(member.id))
                          }
                        >
                          <ShieldOff className="mr-2 h-4 w-4" />
                          Отозвать
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy === member.id}
                          onClick={() =>
                            run(member.id, () => accountsApi.reactivateMember(member.id))
                          }
                        >
                          <UserCheck className="mr-2 h-4 w-4" />
                          Вернуть
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function InvitesCard() {
  const showError = useErrorToast();
  const [invites, setInvites] = useState<Invite[] | null>(null);

  const load = useCallback(async () => {
    try {
      setInvites(await accountsApi.invites());
    } catch (error) {
      showError(error, "Не удалось загрузить приглашения");
    }
  }, [showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const revoke = async (id: string) => {
    try {
      const updated = await accountsApi.revokeInvite(id);
      setInvites((current) => current?.map((i) => (i.id === updated.id ? updated : i)) ?? null);
    } catch (error) {
      showError(error, "Не удалось отозвать приглашение");
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>Приглашения</CardTitle>
          <CardDescription>Ссылки для входа в организацию с заданной ролью.</CardDescription>
        </div>
        <CreateInviteDialog onCreated={(invite) => setInvites((c) => [invite, ...(c ?? [])])} />
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        {invites === null ? (
          <div className="p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : invites.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">Приглашений пока нет.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Роль</TableHead>
                <TableHead>Для кого</TableHead>
                <TableHead>Действует до</TableHead>
                <TableHead>Использовано</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {invites.map((invite) => (
                <TableRow key={invite.id}>
                  <TableCell>{roleLabel(invite.role)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {invite.email ?? "Любой по ссылке"}
                  </TableCell>
                  <TableCell className="text-sm">{formatDate(invite.expires_at)}</TableCell>
                  <TableCell className="text-sm">
                    {invite.uses_count} / {invite.max_uses ?? "∞"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={invite.status === "active" ? "default" : "secondary"}>
                      {INVITE_STATUS_LABELS[invite.status]}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {invite.status === "active" ? (
                      <Button variant="ghost" size="sm" onClick={() => revoke(invite.id)}>
                        Отозвать
                      </Button>
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

export default function OrganizationPage() {
  const { can } = useAuth();
  if (!can("org.members")) {
    return (
      <>
        <PageHeader title="Организация" />
        <p className="text-muted-foreground">
          Управление участниками доступно владельцу организации.
        </p>
      </>
    );
  }
  return (
    <>
      <PageHeader
        title="Организация"
        description="Участники, роли и приглашения. Нанимающему менеджеру можно ограничить доступ отдельными вакансиями."
      />
      <div className="space-y-6">
        <OrganizationCard />
        <MembersCard />
        <InvitesCard />
      </div>
    </>
  );
}
