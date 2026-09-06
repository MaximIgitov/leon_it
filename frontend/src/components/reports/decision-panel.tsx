"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Check, Pause, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { DECISION_LABELS, type Decision } from "@/lib/api/reports";

export function DecisionPanel({ decision, note, disabled, onDecide }: {
  decision: string | null; note: string | null; disabled?: boolean;
  onDecide: (decision: Decision, note: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(note ?? "");
  const [selected, setSelected] = useState<Decision | null>(decision as Decision | null);
  const [pending, setPending] = useState(false);
  useEffect(() => setSelected(decision as Decision | null), [decision]);
  const options = [
    { value: "advance", title: "Следующий этап", text: "Продолжить знакомство", icon: ArrowRight },
    { value: "hold", title: "На паузе", text: "Вернуться к решению позже", icon: Pause },
    { value: "reject", title: "Отказ", text: "Завершить рассмотрение", icon: X },
  ] as const;
  return <section className="report-card decision-panel"><h2>Ваше решение</h2><p className="report-muted">Выберите следующий шаг для кандидата.</p><div className="decision-options" role="group" aria-label="Решение по кандидату">{options.map(option => <button key={option.value} type="button" disabled={disabled || pending} aria-pressed={selected === option.value} data-decision={option.value} onClick={() => setSelected(option.value)}><option.icon size={21} /><span><strong>{option.title}</strong><small>{option.text}</small></span>{selected === option.value && <Check size={18} />}</button>)}</div>
    <Label htmlFor="decision-comment">Комментарий</Label><Textarea id="decision-comment" rows={4} placeholder="Что важно учесть команде" value={draft} disabled={disabled || pending} onChange={event => setDraft(event.target.value)} />
    <footer><Button disabled={disabled || pending || !selected} onClick={async () => { if (!selected) return; setPending(true); try { await onDecide(selected, draft); } finally { setPending(false); } }}>{pending ? "Сохраняем…" : "Сохранить решение"}</Button>{decision && <span>Сохранено: {DECISION_LABELS[decision as Decision] ?? decision}</span>}</footer>
  </section>;
}
