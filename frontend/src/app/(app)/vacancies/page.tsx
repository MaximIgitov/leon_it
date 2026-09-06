"use client";

import { RowsSkeleton, Skeleton } from "@/components/ui/skeleton";

import Link from "@/lib/router";
import { useRouter } from "@/lib/router";
import { useCallback, useEffect, useState } from "react";
import { MessageSquare, Plus, Sparkles } from "lucide-react";

import { openAssistant } from "@/components/assistant/dock";
import { useAuth } from "@/components/auth/auth-provider";
import { Mascot } from "@/components/brand/mascot";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import {
  LEVEL_LABELS,
  VACANCY_STATUS_LABELS,
  vacanciesApi,
  type VacancyListItem,
  type VacancyStatus,
} from "@/lib/api/vacancies";

type Filter = "all" | VacancyStatus;

function statusVariant(status: VacancyStatus): "default" | "secondary" | "outline" {
  if (status === "published") return "default";
  if (status === "draft") return "secondary";
  return "outline";
}

function CreateVacancyDialog() {
  const router = useRouter();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const [sourceText, setSourceText] = useState("");
  const [sourceFile, setSourceFile] = useState<File | null>(null);

  const submit = async () => {
    if (!title.trim()) return;
    setPending(true);
    try {
      const vacancy = await vacanciesApi.create({ title: title.trim(), description });
      router.push(`/vacancies/${vacancy.id}`);
    } catch (error) {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Не удалось создать вакансию",
      });
      setPending(false);
    }
  };

  const submitQuick = async () => {
    if (!sourceFile && sourceText.trim().length < 20) return;
    setPending(true);
    try {
      const result = sourceFile
        ? await vacanciesApi.quickFromFile(sourceFile)
        : await vacanciesApi.quickFromText(sourceText.trim());
      router.push(`/vacancies/${result.vacancy.id}?from=text`);
    } catch (error) {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Не удалось собрать черновик",
      });
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          Новая вакансия
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="font-extrabold">Новая вакансия</DialogTitle>
          <DialogDescription>
            Расскажите, кого ищете. Леон поможет с вопросами.
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="ai">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="ai" className="gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-primary" /> С помощью ИИ
            </TabsTrigger>
            <TabsTrigger value="manual">Вручную</TabsTrigger>
          </TabsList>
          <TabsContent value="ai" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="vacancy-source">Текст вакансии</Label>
              <Textarea
                id="vacancy-source"
                rows={7}
                placeholder="Вставьте вакансию как есть: с hh, из Huntflow или письма нанимающего менеджера"
                value={sourceText}
                onChange={(event) => setSourceText(event.target.value)}
                disabled={sourceFile !== null}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="vacancy-source-file">Или файл: pdf, docx, txt, md, html</Label>
              <Input
                id="vacancy-source-file"
                type="file"
                accept=".pdf,.docx,.txt,.md,.html,.htm"
                onChange={(event) => setSourceFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <DialogFooter className="gap-2 sm:justify-between">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setOpen(false);
                  openAssistant({
                    prompt: "Создай вакансию: название, уровень, ключевые навыки, требования — ",
                  });
                }}
              >
                <MessageSquare className="mr-2 h-4 w-4" />
                Описать ассистенту в чате
              </Button>
              <Button
                onClick={submitQuick}
                disabled={pending || (!sourceFile && sourceText.trim().length < 20)}
              >
                {pending ? <Skeleton className="mr-2 h-4 w-4 rounded-md" /> : <Sparkles className="mr-2 h-4 w-4" />}
                Собрать с ИИ
              </Button>
            </DialogFooter>
          </TabsContent>
          <TabsContent value="manual" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="vacancy-title">Название</Label>
              <Input
                id="vacancy-title"
                placeholder="Например, Python-разработчик (Middle)"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="vacancy-description">Описание</Label>
              <Textarea
                id="vacancy-description"
                rows={5}
                placeholder="Название и описание можно уточнить позже"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
            <DialogFooter>
              <Button onClick={submit} disabled={pending || !title.trim()}>
                {pending ? <Skeleton className="mr-2 h-4 w-4 rounded-md" /> : null}
                Создать
              </Button>
            </DialogFooter>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

export default function VacanciesPage() {
  const { can } = useAuth();
  const { toast } = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [items, setItems] = useState<VacancyListItem[] | null>(null);

  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setItems(await vacanciesApi.list(filter === "all" ? undefined : filter));
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : "Не удалось загрузить вакансии");
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Не удалось загрузить вакансии",
      });
    }
  }, [filter, toast]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Вакансии"
        description="Вакансии вашей команды."
        actions={can("vacancy.write") ? <CreateVacancyDialog /> : undefined}
      />
      <Tabs value={filter} onValueChange={(value) => setFilter(value as Filter)} className="mb-4">
        <TabsList>
          <TabsTrigger value="all">Все</TabsTrigger>
          <TabsTrigger value="published">Опубликованные</TabsTrigger>
          <TabsTrigger value="draft">Черновики</TabsTrigger>
          <TabsTrigger value="archived">Архив</TabsTrigger>
        </TabsList>
      </Tabs>

      {loadError ? <div className="empty-state" role="alert"><Mascot name="think" /><h2>Не получилось загрузить</h2><p>{loadError}</p><Button variant="outline" onClick={() => void load()}>Попробовать снова</Button></div> : items === null ? (
        <RowsSkeleton />
      ) : items.length === 0 ? (
        <div className="empty-state"><Mascot name={filter === "all" ? "mira" : "think"} /><h2>{filter === "all" ? "Создайте первую вакансию" : "Вакансий пока нет"}</h2><p>{filter === "all" ? "Создайте вакансию. Леон поможет подготовить вопросы." : "Вакансий с таким статусом пока нет."}</p></div>
      ) : (
        <ul className="grid gap-3">
          {items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/vacancies/${item.id}`}
                className="vacancy-row"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{item.title}</span>
                    {item.level ? (
                      <span className="vacancy-row-meta text-sm">{LEVEL_LABELS[item.level]}</span>
                    ) : null}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {item.skills.slice(0, 6).map((skill) => (
                      <Badge key={skill} variant="outline" className="font-normal">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="vacancy-row-meta text-sm">
                  {item.question_count}{" "}
                  {item.question_count === 1 ? "вопрос" : item.question_count < 5 ? "вопроса" : "вопросов"}
                </div>
                <Badge variant={statusVariant(item.status)}>{VACANCY_STATUS_LABELS[item.status]}</Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
