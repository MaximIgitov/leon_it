"use client";

import { useState } from "react";
import { ChevronDown, Plus, Trash2 } from "lucide-react";

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
    <Card className="rubric-editor">
      <CardHeader>
        <CardTitle>Рубрика компетенций</CardTitle>
        <CardDescription>
          Задайте навыки, уровни оценки от 1 до 4 и вес каждого навыка.
        </CardDescription>
      </CardHeader>
      <CardContent className="vacancy-form-content">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Компетенций пока нет. Обычно достаточно 3–6: например, «Python», «Базы данных»,
            «Архитектура», «Коммуникация».
          </p>
        ) : null}
        {items.map((item, index) => (
          <details key={item.id || index} className="rubric-item" open={index === 0}>
            <summary><span className="rubric-index">{String(index + 1).padStart(2, "0")}</span><strong>{item.name || "Новый критерий"}</strong><span className="rubric-weight">Вес {item.weight}</span><ChevronDown size={18} /></summary>
            <div className="rubric-fields">
            <div className="rubric-name-row">
              <div className="space-y-1.5">
                <Label htmlFor={`rubric-name-${item.id}`}>Название критерия</Label>
                <Input
                  id={`rubric-name-${item.id}`}
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
                  aria-label={`Удалить критерий ${item.name || index + 1}`}
                  onClick={() => setItems(items.filter((_, i) => i !== index))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              ) : null}
            </div>
            <div className="space-y-2">
              <Label htmlFor={`rubric-description-${item.id}`}>Что оцениваем</Label>
              <Textarea
                id={`rubric-description-${item.id}`}
                rows={2}
                value={item.description}
                disabled={!editable}
                placeholder="Коротко: какие знания и поведение относятся к этой компетенции"
                onChange={(e) => update(index, { description: e.target.value })}
              />
            </div>
            <div className="rubric-levels">
              {["1", "2", "3", "4"].map((level) => (
                <div key={level} className="rubric-level">
                  <Label htmlFor={`rubric-${item.id}-${level}`}>Уровень {level}</Label>
                  <Textarea
                    id={`rubric-${item.id}-${level}`}
                    rows={2}
                    value={item.levels[level] ?? ""}
                    placeholder={LEVEL_HINTS[level]}
                    disabled={!editable}
                    onChange={(e) => update(index, { levels: { ...item.levels, [level]: e.target.value } })}
                  />
                </div>
              ))}
            </div>
            </div>
          </details>
        ))}
        {editable ? (
          <div className="editor-save-bar flex flex-wrap items-center justify-between gap-3">
            <Button variant="outline" onClick={add}>
              <Plus className="mr-2 h-4 w-4" />
              Добавить критерий
            </Button>
            <SaveBar pending={pending} dirty={dirty} onSave={save} onReset={() => setItems(vacancy.rubric)} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
