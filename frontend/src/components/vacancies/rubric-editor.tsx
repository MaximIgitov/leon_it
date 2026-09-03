"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { SaveBar, type EditorProps } from "@/components/vacancies/vacancy-editors";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { vacanciesApi, type RubricCompetency } from "@/lib/api/vacancies";

const LEVEL_HINTS: Record<string, string> = {
  "1": "Не владеет: путается в базовых понятиях",
  "2": "Базово: знает термины, применяет с подсказкой",
  "3": "Уверенно: самостоятельно решает типовые задачи",
  "4": "Эксперт: объясняет устройство и границы применимости",
};

function slugify(name: string, taken: Set<string>): string {
  const base =
    name
      .toLowerCase()
      .replace(/[^a-z0-9а-яё]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "competency";
  let candidate = base;
  let counter = 2;
  while (taken.has(candidate)) candidate = `${base}-${counter++}`;
  return candidate;
}

export function RubricEditor({ vacancy, editable, onSaved, onError }: EditorProps) {
  const { toast } = useToast();
  const [items, setItems] = useState<RubricCompetency[]>(vacancy.rubric);
  const [pending, setPending] = useState(false);
  const dirty = JSON.stringify(items) !== JSON.stringify(vacancy.rubric);

  const update = (index: number, patch: Partial<RubricCompetency>) =>
    setItems(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  const add = () => {
    const taken = new Set(items.map((item) => item.id));
    setItems([
      ...items,
      { id: slugify(`competency-${items.length + 1}`, taken), name: "", description: "", weight: 3, levels: {} },
    ]);
  };

  const save = async () => {
    const cleaned = items
      .filter((item) => item.name.trim())
      .map((item, index, all) => ({
        ...item,
        name: item.name.trim(),
        id: item.id || slugify(item.name, new Set(all.slice(0, index).map((i) => i.id))),
      }));
    setPending(true);
    try {
      const updated = await vacanciesApi.update(vacancy.id, { rubric: cleaned });
      onSaved(updated);
      setItems(updated.rubric);
      toast({ title: "Рубрика сохранена" });
    } catch (error) {
      onError(error, "Не удалось сохранить рубрику");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Рубрика компетенций</CardTitle>
        <CardDescription>
          По этим компетенциям модель ставит баллы 1–4. Якорные описания уровней делают оценку
          воспроизводимой: без них модель трактует «хорошо» по-своему. Вес задаёт вклад в общий балл.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Компетенций пока нет. Обычно достаточно 3–6: например, «Python», «Базы данных»,
            «Архитектура», «Коммуникация».
          </p>
        ) : null}
        {items.map((item, index) => (
          <div key={item.id || index} className="rounded-lg border p-4">
            <div className="grid gap-3 sm:grid-cols-[1fr_140px_auto]">
              <div className="space-y-1.5">
                <Label>Компетенция</Label>
                <Input
                  value={item.name}
                  placeholder="Название"
                  disabled={!editable}
                  onChange={(e) => update(index, { name: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Вес</Label>
                <Select
                  value={String(item.weight)}
                  disabled={!editable}
                  onValueChange={(v) => update(index, { weight: Number(v) })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[1, 2, 3, 4, 5].map((w) => (
                      <SelectItem key={w} value={String(w)}>
                        {w}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {editable ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="self-end"
                  aria-label="Удалить компетенцию"
                  onClick={() => setItems(items.filter((_, i) => i !== index))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              ) : null}
            </div>
            <div className="mt-3 space-y-1.5">
              <Label>Что оцениваем</Label>
              <Textarea
                rows={2}
                value={item.description}
                disabled={!editable}
                placeholder="Коротко: какие знания и поведение относятся к этой компетенции"
                onChange={(e) => update(index, { description: e.target.value })}
              />
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {["1", "2", "3", "4"].map((level) => (
                <div key={level} className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Уровень {level}</Label>
                  <Input
                    value={item.levels[level] ?? ""}
                    placeholder={LEVEL_HINTS[level]}
                    disabled={!editable}
                    onChange={(e) => update(index, { levels: { ...item.levels, [level]: e.target.value } })}
                  />
                </div>
              ))}
            </div>
          </div>
        ))}
        {editable ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={add}>
              <Plus className="mr-2 h-4 w-4" />
              Добавить компетенцию
            </Button>
            <SaveBar pending={pending} dirty={dirty} onSave={save} onReset={() => setItems(vacancy.rubric)} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
