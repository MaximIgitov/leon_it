"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, FileText, Loader2, Search, Trash2, Upload } from "lucide-react";

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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import {
  describeKind,
  formatSize,
  knowledgeApi,
  parseTags,
  type KnowledgeDocument,
  type KnowledgeDocumentDetail,
  type KnowledgeFormats,
  type KnowledgeHit,
} from "@/lib/api/knowledge";

function formatDate(value: string): string {
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function AddDocumentCard({
  formats,
  onAdded,
}: {
  formats: KnowledgeFormats | null;
  onAdded: () => Promise<void>;
}) {
  const { toast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileTitle, setFileTitle] = useState("");
  const [fileTags, setFileTags] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [tags, setTags] = useState("");
  const [pending, setPending] = useState(false);

  const fail = (error: unknown, fallback: string) =>
    toast({
      variant: "destructive",
      title: error instanceof ApiError ? error.message : fallback,
    });

  const submitFile = async () => {
    if (!file) return;
    setPending(true);
    try {
      const document = await knowledgeApi.upload(file, { title: fileTitle.trim(), tags: fileTags });
      toast({
        title: `Документ «${document.title}» добавлен`,
        description: `Фрагментов для поиска: ${document.chunk_count}`,
      });
      setFile(null);
      setFileTitle("");
      setFileTags("");
      if (fileInput.current) fileInput.current.value = "";
      await onAdded();
    } catch (error) {
      fail(error, "Не удалось загрузить файл");
    } finally {
      setPending(false);
    }
  };

  const submitText = async () => {
    if (!title.trim() || !text.trim()) return;
    setPending(true);
    try {
      const document = await knowledgeApi.createText({
        title: title.trim(),
        text,
        tags: parseTags(tags),
      });
      toast({
        title: `Документ «${document.title}» добавлен`,
        description: `Фрагментов для поиска: ${document.chunk_count}`,
      });
      setTitle("");
      setText("");
      setTags("");
      await onAdded();
    } catch (error) {
      fail(error, "Не удалось сохранить документ");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Добавить документ</CardTitle>
        <CardDescription>
          {formats
            ? `Форматы: ${formats.extensions.join(", ")} до ${formats.max_file_mb} МБ. Сканы и картинки пока не распознаются.`
            : "Файл или текст: описание компании, продукты, стек, условия, этапы найма."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="file">
          <TabsList>
            <TabsTrigger value="file">
              <Upload className="mr-2 h-4 w-4" />
              Файл
            </TabsTrigger>
            <TabsTrigger value="text">
              <FileText className="mr-2 h-4 w-4" />
              Текст
            </TabsTrigger>
          </TabsList>
          <TabsContent value="file" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="knowledge-file">Файл</Label>
              <Input
                id="knowledge-file"
                ref={fileInput}
                type="file"
                accept={formats?.extensions.join(",")}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="knowledge-file-title">Название (необязательно)</Label>
                <Input
                  id="knowledge-file-title"
                  placeholder="По умолчанию — имя файла"
                  value={fileTitle}
                  onChange={(event) => setFileTitle(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="knowledge-file-tags">Теги через запятую</Label>
                <Input
                  id="knowledge-file-tags"
                  placeholder="hr, продукты, стек"
                  value={fileTags}
                  onChange={(event) => setFileTags(event.target.value)}
                />
              </div>
            </div>
            <Button onClick={submitFile} disabled={pending || !file}>
              {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Загрузить
            </Button>
          </TabsContent>
          <TabsContent value="text" className="space-y-4 pt-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="knowledge-title">Название</Label>
                <Input
                  id="knowledge-title"
                  placeholder="Например, Этапы найма"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="knowledge-tags">Теги через запятую</Label>
                <Input
                  id="knowledge-tags"
                  placeholder="hr, найм"
                  value={tags}
                  onChange={(event) => setTags(event.target.value)}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="knowledge-text">Текст</Label>
              <Textarea
                id="knowledge-text"
                rows={8}
                placeholder="Вставьте текст: абзацы станут фрагментами для поиска"
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
            </div>
            <Button onClick={submitText} disabled={pending || !title.trim() || !text.trim()}>
              {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Сохранить
            </Button>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function SearchCard({ total }: { total: number }) {
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<KnowledgeHit[] | null>(null);
  const [pending, setPending] = useState(false);

  const run = async () => {
    if (!query.trim()) return;
    setPending(true);
    try {
      setHits((await knowledgeApi.search(query.trim(), 6)).hits);
    } catch (error) {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Поиск не удался",
      });
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Проверить поиск</CardTitle>
        <CardDescription>
          Так же ищет ассистент, когда его спрашивают о компании. Документов в базе: {total}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void run();
          }}
        >
          <Input
            placeholder="Например, этапы найма или стек бэкенда"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Поисковый запрос"
          />
          <Button type="submit" variant="secondary" disabled={pending || !query.trim()}>
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            <span className="ml-2">Найти</span>
          </Button>
        </form>
        {hits === null ? null : hits.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ничего не нашлось. Попробуйте другие слова.</p>
        ) : (
          <ul className="space-y-3">
            {hits.map((hit) => (
              <li key={`${hit.document_id}-${hit.position}`} className="rounded-md border p-3 text-sm">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="font-medium">{hit.title}</span>
                  <Badge variant="outline">фрагмент {hit.position + 1}</Badge>
                </div>
                <p className="whitespace-pre-line text-muted-foreground">{hit.text}</p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function DocumentsCard({
  items,
  canWrite,
  onChanged,
}: {
  items: KnowledgeDocument[] | null;
  canWrite: boolean;
  onChanged: () => Promise<void>;
}) {
  const { toast } = useToast();
  const [opened, setOpened] = useState<KnowledgeDocumentDetail | null>(null);

  const open = async (id: string) => {
    try {
      setOpened(await knowledgeApi.get(id));
    } catch (error) {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Не удалось открыть документ",
      });
    }
  };

  const remove = async (document: KnowledgeDocument) => {
    try {
      await knowledgeApi.remove(document.id);
      toast({ title: `Документ «${document.title}» удалён` });
      await onChanged();
    } catch (error) {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Не удалось удалить документ",
      });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Документы</CardTitle>
        <CardDescription>
          Что знает ассистент о компании. Названия и теги помогают поиску, поэтому называйте по
          сути: «Этапы найма», «Стек бэкенда».
        </CardDescription>
      </CardHeader>
      <CardContent>
        {items === null ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Загружаем…
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            База пуста. Добавьте описание компании, продукты, стек и условия работы — ассистент
            начнёт отвечать по ним, а черновики вакансий станут точнее.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Название</TableHead>
                  <TableHead>Вид</TableHead>
                  <TableHead>Теги</TableHead>
                  <TableHead className="text-right">Фрагментов</TableHead>
                  <TableHead>Обновлён</TableHead>
                  <TableHead className="text-right">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((document) => (
                  <TableRow key={document.id}>
                    <TableCell>
                      <button
                        type="button"
                        className="text-left font-medium hover:underline"
                        onClick={() => void open(document.id)}
                      >
                        {document.title}
                      </button>
                      <p className="line-clamp-1 text-xs text-muted-foreground">{document.preview}</p>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm">
                      {describeKind(document)} · {formatSize(document.size_bytes)}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {document.tags.map((tag) => (
                          <Badge key={tag} variant="secondary">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{document.chunk_count}</TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {formatDate(document.updated_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {canWrite ? (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="ghost" size="sm" aria-label="Удалить документ">
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Удалить «{document.title}»?</AlertDialogTitle>
                              <AlertDialogDescription>
                                Ассистент перестанет видеть этот документ. Исходный файл тоже
                                удалится.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Отмена</AlertDialogCancel>
                              <AlertDialogAction onClick={() => void remove(document)}>
                                Удалить
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
      <Dialog open={opened !== null} onOpenChange={(open) => !open && setOpened(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
          {opened ? (
            <>
              <DialogHeader>
                <DialogTitle>{opened.title}</DialogTitle>
                <DialogDescription>
                  {describeKind(opened)} · {formatSize(opened.size_bytes)} · фрагментов:{" "}
                  {opened.chunk_count} · добавил(а) {opened.created_by_label || "—"}
                </DialogDescription>
              </DialogHeader>
              <pre className="whitespace-pre-wrap break-words font-sans text-sm">{opened.text}</pre>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </Card>
  );
}

export default function KnowledgePage() {
  const { can } = useAuth();
  const { toast } = useToast();
  const [items, setItems] = useState<KnowledgeDocument[] | null>(null);
  const [formats, setFormats] = useState<KnowledgeFormats | null>(null);
  const canWrite = can("knowledge.write");

  const load = useCallback(async () => {
    try {
      setItems(await knowledgeApi.list());
    } catch (error) {
      toast({
        variant: "destructive",
        title: error instanceof ApiError ? error.message : "Не удалось загрузить базу знаний",
      });
    }
  }, [toast]);

  useEffect(() => {
    void load();
    knowledgeApi
      .formats()
      .then(setFormats)
      .catch(() => setFormats(null));
  }, [load]);

  return (
    <>
      <PageHeader
        title="База знаний"
        description="Документы о компании для ассистента и генерации вакансий: продукты, клиенты, стек, ценности, этапы найма, условия. Поиск лексический, документы не покидают вашу организацию."
      />
      <div className="space-y-6">
        {canWrite ? <AddDocumentCard formats={formats} onAdded={load} /> : null}
        <DocumentsCard items={items} canWrite={canWrite} onChanged={load} />
        <SearchCard total={items?.length ?? 0} />
        {!canWrite ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <BookOpen className="h-4 w-4" /> Пополнять базу может рекрутёр или владелец организации.
          </p>
        ) : null}
      </div>
    </>
  );
}
