"use client";

import { useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { SaveBar, type EditorProps } from "@/components/vacancies/vacancy-editors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { vacanciesApi, type QuestionDraft } from "@/lib/api/vacancies";

function emptyQuestion(): QuestionDraft {
  return {
    kind: "video",
    text: "",
    expected_points: [],
    competency_ids: [],
    allows_followup: false,
    prep_seconds: null,
    max_answer_seconds: null,
    retakes_allowed: null,
  };
}

function toDrafts(vacancy: EditorProps["vacancy"]): QuestionDraft[] {
  return vacancy.questions.map((q) => ({
    id: q.id,
    kind: q.kind,
    text: q.text,
    expected_points: q.expected_points,
    competency_ids: q.competency_ids,
    allows_followup: q.allows_followup,
    prep_seconds: q.prep_seconds,
    max_answer_seconds: q.max_answer_seconds,
    retakes_allowed: q.retakes_allowed,
  }));
}

function optionalNumber(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function QuestionsEditor({ vacancy, editable, onSaved, onError }: EditorProps) {
  const { toast } = useToast();
  const [items, setItems] = useState<QuestionDraft[]>(() => toDrafts(vacancy));
  const [pending, setPending] = useState(false);
  const dirty = JSON.stringify(items) !== JSON.stringify(toDrafts(vacancy));
  const competencies = vacancy.rubric;

  const update = (index: number, patch: Partial<QuestionDraft>) =>
    setItems(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    setItems(next);
  };

  const save = async () => {
    const cleaned = items
      .map((item) => ({ ...item, text: item.text.trim() }))
      .filter((item) => item.text);
    setPending(true);
    try {
      const updated = await vacanciesApi.replaceQuestions(vacancy.id, cleaned);
      onSaved(updated);
      setItems(toDrafts(updated));
      toast({ title: "Вопросы сохранены" });
    } catch (error) {
      onError(error, "Не удалось сохранить вопросы");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Вопросы интервью</CardTitle>
        <CardDescription>
          Кандидат видит и слышит вопросы по одному в этом порядке. «Что должен покрыть ответ»
          видит только модель-оценщик. Лимиты времени наследуются из настроек интервью, если не
          заданы здесь.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.map((item, index) => (
          <div key={item.id ?? `new-${index}`} className="rounded-lg border p-4">
            <div className="flex items-start gap-3">
              <span className="mt-2 w-6 shrink-0 text-sm font-semibold text-muted-foreground">
                {index + 1}.
              </span>
              <div className="min-w-0 flex-1 space-y-3">
                <Textarea
                  rows={2}
                  value={item.text}
                  disabled={!editable}
                  placeholder="Текст вопроса так, как его услышит кандидат"
                  onChange={(e) => update(index, { text: e.target.value })}
                />
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    Что должен покрыть хороший ответ (по пункту на строку)
                  </Label>
                  <Textarea
                    rows={2}
                    value={item.expected_points.join("\n")}
                    disabled={!editable}
                    onChange={(e) => update(index, { expected_points: e.target.value.split("\n") })}
                  />
                </div>
                {competencies.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {competencies.map((competency) => {
                      const selected = item.competency_ids.includes(competency.id);
                      return (
                        <button
                          key={competency.id}
                          type="button"
                          disabled={!editable}
                          aria-pressed={selected}
                          onClick={() =>
                            update(index, {
                              competency_ids: selected
                                ? item.competency_ids.filter((id) => id !== competency.id)
                                : [...item.competency_ids, competency.id],
                            })
                          }
                        >
                          <Badge variant={selected ? "default" : "outline"} className="font-normal">
                            {competency.name}
                          </Badge>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Добавьте компетенции в рубрике, чтобы привязать вопрос к ним.
                  </p>
                )}
                <div className="grid gap-3 sm:grid-cols-4">
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Подготовка, с</Label>
                    <Input
                      type="number"
                      min={0}
                      max={600}
                      placeholder={String(vacancy.settings.prep_seconds)}
                      value={item.prep_seconds ?? ""}
                      disabled={!editable}
                      onChange={(e) => update(index, { prep_seconds: optionalNumber(e.target.value) })}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Ответ, с</Label>
                    <Input
                      type="number"
                      min={30}
                      max={900}
                      placeholder={String(vacancy.settings.max_answer_seconds)}
                      value={item.max_answer_seconds ?? ""}
                      disabled={!editable}
                      onChange={(e) => update(index, { max_answer_seconds: optionalNumber(e.target.value) })}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Перезаписей</Label>
                    <Input
                      type="number"
                      min={0}
                      max={5}
                      placeholder={String(vacancy.settings.retakes_allowed)}
                      value={item.retakes_allowed ?? ""}
                      disabled={!editable}
                      onChange={(e) => update(index, { retakes_allowed: optionalNumber(e.target.value) })}
                    />
                  </div>
                  <label className="flex items-center gap-2 self-end pb-2 text-sm">
                    <Checkbox
                      checked={item.allows_followup}
                      disabled={!editable}
                      onCheckedChange={(checked) => update(index, { allows_followup: checked === true })}
                    />
                    Допускает уточнение
                  </label>
                </div>
              </div>
              {editable ? (
                <div className="flex shrink-0 flex-col gap-1">
                  <Button variant="ghost" size="icon" aria-label="Выше" disabled={index === 0} onClick={() => move(index, -1)}>
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="icon" aria-label="Ниже" disabled={index === items.length - 1} onClick={() => move(index, 1)}>
                    <ArrowDown className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="icon" aria-label="Удалить вопрос" onClick={() => setItems(items.filter((_, i) => i !== index))}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {editable ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => setItems([...items, emptyQuestion()])}>
              <Plus className="mr-2 h-4 w-4" />
              Добавить вопрос
            </Button>
            <SaveBar pending={pending} dirty={dirty} onSave={save} onReset={() => setItems(toDrafts(vacancy))} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
