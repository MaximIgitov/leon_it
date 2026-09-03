"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Loader2, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { candidatesApi, interviewsApi, type Interview } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";
import { vacanciesApi, type VacancyListItem } from "@/lib/api/vacancies";

export function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex gap-2">
      <Input readOnly value={value} onFocus={(e) => e.target.select()} />
      <Button
        variant="outline"
        aria-label="Скопировать"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
          } catch {
            /* буфер недоступен */
          }
        }}
      >
        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      </Button>
    </div>
  );
}

export function InviteDialog({
  vacancyId,
  trigger,
  onInvited,
}: {
  /** Если задана — вакансия зафиксирована, иначе выбирается в диалоге. */
  vacancyId?: string;
  trigger?: React.ReactNode;
  onInvited?: (interview: Interview) => void;
}) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [vacancies, setVacancies] = useState<VacancyListItem[]>([]);
  const [selectedVacancy, setSelectedVacancy] = useState(vacancyId ?? "");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [bulk, setBulk] = useState("");
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<{ link?: string; summary: string } | null>(null);

  useEffect(() => {
    if (!open || vacancyId) return;
    vacanciesApi
      .list("published")
      .then((items) => {
        setVacancies(items);
        if (!selectedVacancy && items[0]) setSelectedVacancy(items[0].id);
      })
      .catch(() => undefined);
  }, [open, vacancyId, selectedVacancy]);

  const fail = (error: unknown, fallback: string) =>
    toast({ variant: "destructive", title: error instanceof ApiError ? error.message : fallback });

  const inviteOne = async () => {
    setPending(true);
    try {
      const interview = await interviewsApi.invite({
        vacancy_id: selectedVacancy,
        full_name: fullName.trim(),
        email: email.trim(),
      });
      setResult({ link: interview.link ?? undefined, summary: "Приглашение отправлено на e-mail." });
      onInvited?.(interview);
    } catch (error) {
      fail(error, "Не удалось пригласить кандидата");
    } finally {
      setPending(false);
    }
  };

  const inviteMany = async () => {
    setPending(true);
    try {
      const outcome = await candidatesApi.bulkCreate({ text: bulk, vacancy_id: selectedVacancy });
      setResult({
        summary: `Приглашено: ${outcome.invited}. Новых кандидатов: ${outcome.created.length}, уже были: ${outcome.existing.length}${outcome.skipped_lines ? `, строк без e-mail: ${outcome.skipped_lines}` : ""}.`,
      });
      onInvited?.({} as Interview);
    } catch (error) {
      fail(error, "Не удалось добавить кандидатов");
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setResult(null);
          setFullName("");
          setEmail("");
          setBulk("");
        }
      }}
    >
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            <Send className="mr-2 h-4 w-4" />
            Пригласить
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Пригласить на интервью</DialogTitle>
          <DialogDescription>
            Кандидат получит письмо со ссылкой. Ссылка показывается один раз — её можно
            отправить и вручную.
          </DialogDescription>
        </DialogHeader>
        {result ? (
          <div className="space-y-3">
            <p className="text-sm">{result.summary}</p>
            {result.link ? <CopyField value={result.link} /> : null}
          </div>
        ) : (
          <div className="space-y-4">
            {!vacancyId ? (
              <div className="space-y-2">
                <Label>Вакансия</Label>
                <Select value={selectedVacancy} onValueChange={setSelectedVacancy}>
                  <SelectTrigger>
                    <SelectValue placeholder="Выберите опубликованную вакансию" />
                  </SelectTrigger>
                  <SelectContent>
                    {vacancies.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        {v.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {vacancies.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Нет опубликованных вакансий.</p>
                ) : null}
              </div>
            ) : null}
            <Tabs defaultValue="one">
              <TabsList>
                <TabsTrigger value="one">Один кандидат</TabsTrigger>
                <TabsTrigger value="many">Списком</TabsTrigger>
              </TabsList>
              <TabsContent value="one" className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="invite-name">Имя и фамилия</Label>
                  <Input id="invite-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="invite-email">E-mail</Label>
                  <Input id="invite-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
                </div>
                <Button
                  className="w-full"
                  disabled={pending || !selectedVacancy || !fullName.trim() || !email.trim()}
                  onClick={inviteOne}
                >
                  {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                  Пригласить
                </Button>
              </TabsContent>
              <TabsContent value="many" className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="invite-bulk">По кандидату на строку: «Имя Фамилия, email» или просто email</Label>
                  <Textarea
                    id="invite-bulk"
                    rows={6}
                    placeholder={"Анна Иванова, anna@example.com\npetr@example.com"}
                    value={bulk}
                    onChange={(e) => setBulk(e.target.value)}
                  />
                </div>
                <Button className="w-full" disabled={pending || !selectedVacancy || !bulk.trim()} onClick={inviteMany}>
                  {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                  Добавить и пригласить
                </Button>
              </TabsContent>
            </Tabs>
          </div>
        )}
        {result ? (
          <DialogFooter>
            <Button onClick={() => setOpen(false)}>Готово</Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
