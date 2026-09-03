"use client";

import { useState } from "react";
import { Archive, ArchiveRestore, Loader2, Send, Undo2, X } from "lucide-react";

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
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  LEVEL_LABELS,
  vacanciesApi,
  type Vacancy,
  type VacancyLevel,
} from "@/lib/api/vacancies";

export type EditorProps = {
  vacancy: Vacancy;
  editable: boolean;
  onSaved: (vacancy: Vacancy) => void;
  onError: (error: unknown, fallback: string) => void;
};

export function SaveBar({
  pending,
  dirty,
  onSave,
  onReset,
}: {
  pending: boolean;
  dirty: boolean;
  onSave: () => void;
  onReset: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Button onClick={onSave} disabled={pending || !dirty}>
        {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Сохранить
      </Button>
      {dirty ? (
        <Button variant="ghost" onClick={onReset} disabled={pending}>
          <Undo2 className="mr-2 h-4 w-4" />
          Отменить
        </Button>
      ) : null}
    </div>
  );
}

export function VacancyDescriptionEditor({ vacancy, editable, onSaved, onError }: EditorProps) {
  const { toast } = useToast();
  const [title, setTitle] = useState(vacancy.title);
  const [description, setDescription] = useState(vacancy.description);
  const [requirements, setRequirements] = useState(vacancy.requirements);
  const [skills, setSkills] = useState<string[]>(vacancy.skills);
  const [skillInput, setSkillInput] = useState("");
  const [level, setLevel] = useState<VacancyLevel | "none">(vacancy.level ?? "none");
  const [pending, setPending] = useState(false);

  const dirty =
    title !== vacancy.title ||
    description !== vacancy.description ||
    requirements !== vacancy.requirements ||
    JSON.stringify(skills) !== JSON.stringify(vacancy.skills) ||
    (level === "none" ? null : level) !== vacancy.level;

  const reset = () => {
    setTitle(vacancy.title);
    setDescription(vacancy.description);
    setRequirements(vacancy.requirements);
    setSkills(vacancy.skills);
    setLevel(vacancy.level ?? "none");
  };

  const addSkill = () => {
    const value = skillInput.trim();
    if (!value) return;
    if (!skills.some((s) => s.toLowerCase() === value.toLowerCase())) setSkills([...skills, value]);
    setSkillInput("");
  };

  const save = async () => {
    setPending(true);
    try {
      const updated = await vacanciesApi.update(vacancy.id, {
        title: title.trim(),
        description,
        requirements,
        skills,
        level: level === "none" ? null : level,
      });
      onSaved(updated);
      toast({ title: "Описание сохранено" });
    } catch (error) {
      onError(error, "Не удалось сохранить описание");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Описание вакансии</CardTitle>
        <CardDescription>
          Описание и требования читает модель-оценщик: чем конкретнее требования, тем точнее
          заключение. Навыки подсказывают распознаванию речи термины.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
          <div className="space-y-2">
            <Label htmlFor="title">Название</Label>
            <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} disabled={!editable} />
          </div>
          <div className="space-y-2">
            <Label>Уровень</Label>
            <Select value={level} onValueChange={(v) => setLevel(v as VacancyLevel | "none")} disabled={!editable}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Не указан</SelectItem>
                {(Object.keys(LEVEL_LABELS) as VacancyLevel[]).map((value) => (
                  <SelectItem key={value} value={value}>
                    {LEVEL_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="description">Описание</Label>
          <Textarea id="description" rows={8} value={description} onChange={(e) => setDescription(e.target.value)} disabled={!editable} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="requirements">Требования к кандидату</Label>
          <Textarea
            id="requirements"
            rows={6}
            placeholder="Обязательные и желательные требования — по пунктам"
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
            disabled={!editable}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="skill">Ключевые навыки</Label>
          <div className="flex flex-wrap gap-1.5">
            {skills.map((skill) => (
              <Badge key={skill} variant="secondary" className="gap-1 pr-1 font-normal">
                {skill}
                {editable ? (
                  <button
                    type="button"
                    aria-label={`Убрать ${skill}`}
                    className="rounded-full p-0.5 hover:bg-background"
                    onClick={() => setSkills(skills.filter((s) => s !== skill))}
                  >
                    <X className="h-3 w-3" />
                  </button>
                ) : null}
              </Badge>
            ))}
          </div>
          {editable ? (
            <Input
              id="skill"
              placeholder="Введите навык и нажмите Enter"
              value={skillInput}
              onChange={(e) => setSkillInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addSkill();
                }
              }}
              onBlur={addSkill}
            />
          ) : null}
        </div>
        {editable ? <SaveBar pending={pending} dirty={dirty} onSave={save} onReset={reset} /> : null}
      </CardContent>
    </Card>
  );
}

export function VacancyStatusActions({
  vacancy,
  onChange,
  onError,
}: {
  vacancy: Vacancy;
  onChange: (vacancy: Vacancy) => void;
  onError: (error: unknown, fallback: string) => void;
}) {
  const { toast } = useToast();
  const [pending, setPending] = useState(false);

  const run = async (action: () => Promise<Vacancy>, success: string, fallback: string) => {
    setPending(true);
    try {
      onChange(await action());
      toast({ title: success });
    } catch (error) {
      onError(error, fallback);
    } finally {
      setPending(false);
    }
  };

  if (vacancy.status === "archived") {
    return (
      <Button variant="outline" size="sm" disabled={pending} onClick={() => run(() => vacanciesApi.restore(vacancy.id), "Вакансия возвращена в черновики", "Не удалось восстановить")}>
        <ArchiveRestore className="mr-2 h-4 w-4" />
        Восстановить
      </Button>
    );
  }
  return (
    <>
      {vacancy.status === "published" ? (
        <Button variant="outline" size="sm" disabled={pending} onClick={() => run(() => vacanciesApi.unpublish(vacancy.id), "Вакансия снята с публикации", "Не удалось снять с публикации")}>
          Снять с публикации
        </Button>
      ) : (
        <Button size="sm" disabled={pending} onClick={() => run(() => vacanciesApi.publish(vacancy.id), "Вакансия опубликована — можно приглашать кандидатов", "Не удалось опубликовать")}>
          <Send className="mr-2 h-4 w-4" />
          Опубликовать
        </Button>
      )}
      <Button variant="ghost" size="sm" disabled={pending} onClick={() => run(() => vacanciesApi.archive(vacancy.id), "Вакансия перенесена в архив", "Не удалось архивировать")}>
        <Archive className="mr-2 h-4 w-4" />В архив
      </Button>
    </>
  );
}
