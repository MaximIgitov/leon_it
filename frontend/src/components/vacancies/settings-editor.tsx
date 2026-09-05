"use client";

import { useState } from "react";

import { SaveBar, type EditorProps } from "@/components/vacancies/vacancy-editors";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  FEEDBACK_MODE_LABELS,
  INTERVIEW_MODE_HINTS,
  INTERVIEW_MODE_LABELS,
  vacanciesApi,
  type FeedbackMode,
  type InterviewMode,
  type InterviewSettings,
} from "@/lib/api/vacancies";

function NumberField({
  id,
  label,
  hint,
  value,
  min,
  max,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-start justify-between gap-4 rounded-lg border p-3">
      <span>
        <span className="block text-sm font-medium">{label}</span>
        <span className="block text-xs text-muted-foreground">{hint}</span>
      </span>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </label>
  );
}

export function avatarHint(available: boolean): string {
  return available
    ? "Виртуальный интервьюер произносит вопросы на видео. Клипы готовятся один раз при публикации; у провайдера это около доллара за минуту видео"
    : "На этом сервере провайдер аватара не настроен: кандидат видит персону LeonIT с озвучкой";
}

export function SettingsEditor({ vacancy, editable, onSaved, onError }: EditorProps) {
  const { toast } = useToast();
  const [settings, setSettings] = useState<InterviewSettings>(vacancy.settings);
  const [pending, setPending] = useState(false);
  const dirty = JSON.stringify(settings) !== JSON.stringify(vacancy.settings);
  const patch = (partial: Partial<InterviewSettings>) => setSettings({ ...settings, ...partial });

  const save = async () => {
    setPending(true);
    try {
      const updated = await vacanciesApi.update(vacancy.id, { settings });
      onSaved(updated);
      setSettings(updated.settings);
      toast({ title: "Настройки интервью сохранены" });
    } catch (error) {
      onError(error, "Не удалось сохранить настройки");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Настройки интервью</CardTitle>
        <CardDescription>
          Как проходит интервью для кандидата этой вакансии. Лимиты можно переопределить у
          отдельного вопроса.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-1.5">
          <Label htmlFor="intro">Вступление для кандидата</Label>
          <Textarea
            id="intro"
            rows={3}
            value={settings.intro_text}
            disabled={!editable}
            placeholder="Пара фраз о команде и о том, чего ждать от интервью"
            onChange={(e) => patch({ intro_text: e.target.value })}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Формат интервью</Label>
            <Select value={settings.interview_mode} disabled={!editable} onValueChange={(v) => patch({ interview_mode: v as InterviewMode })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(INTERVIEW_MODE_LABELS) as InterviewMode[]).map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {INTERVIEW_MODE_LABELS[mode]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{INTERVIEW_MODE_HINTS[settings.interview_mode]}</p>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <NumberField id="prep" label="Подготовка к ответу, с" hint={settings.interview_mode === "live" ? "В живом диалоге не используется: запись начинается, как только прозвучал вопрос" : undefined} value={settings.prep_seconds} min={0} max={600} disabled={!editable} onChange={(v) => patch({ prep_seconds: v })} />
          <NumberField id="answer" label="Ответ не дольше, с" value={settings.max_answer_seconds} min={30} max={900} disabled={!editable} onChange={(v) => patch({ max_answer_seconds: v })} />
          <NumberField id="retakes" label="Перезаписей ответа" hint={settings.interview_mode === "live" ? "В живом диалоге перезаписи нет" : "0 — одна попытка"} value={settings.retakes_allowed} min={0} max={5} disabled={!editable} onChange={(v) => patch({ retakes_allowed: v })} />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <ToggleRow label="Тренировочный вопрос" hint="Перед первым вопросом кандидат проверяет запись на пробном вопросе" checked={settings.practice_question_enabled} disabled={!editable} onChange={(v) => patch({ practice_question_enabled: v })} />
          <ToggleRow label="Озвучивать вопросы" hint="Вопрос читается синтезированным голосом; текст показывается всегда" checked={settings.tts_enabled} disabled={!editable} onChange={(v) => patch({ tts_enabled: v })} />
          <ToggleRow label="Уточняющие вопросы" hint="Один уточняющий вопрос после основных — по вопросам с пометкой «допускает уточнение»" checked={settings.followups_enabled} disabled={!editable} onChange={(v) => patch({ followups_enabled: v })} />
          <ToggleRow label="ИИ-аватар интервьюера" hint={avatarHint(Boolean(vacancy.avatar_available))} checked={settings.avatar_enabled} disabled={!editable || !vacancy.avatar_available} onChange={(v) => patch({ avatar_enabled: v })} />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <NumberField id="invitation" label="Ссылка действует, дней" value={settings.invitation_days} min={1} max={60} disabled={!editable} onChange={(v) => patch({ invitation_days: v })} />
          <div className="space-y-1.5">
            <Label>Обратная связь кандидату</Label>
            <Select value={settings.candidate_feedback_mode} disabled={!editable} onValueChange={(v) => patch({ candidate_feedback_mode: v as FeedbackMode })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(FEEDBACK_MODE_LABELS) as FeedbackMode[]).map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {FEEDBACK_MODE_LABELS[mode]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Кандидат получает советы по развитию — без балла и рекомендации.
            </p>
          </div>
          {settings.candidate_feedback_mode === "auto_after_days" ? (
            <NumberField id="feedback-days" label="Через сколько дней" value={settings.candidate_feedback_after_days} min={1} max={30} disabled={!editable} onChange={(v) => patch({ candidate_feedback_after_days: v })} />
          ) : null}
        </div>

        {editable ? <SaveBar pending={pending} dirty={dirty} onSave={save} onReset={() => setSettings(vacancy.settings)} /> : null}
      </CardContent>
    </Card>
  );
}
