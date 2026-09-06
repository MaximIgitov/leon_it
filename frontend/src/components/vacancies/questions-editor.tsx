"use client";

import { useState } from "react";
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronDown, GripVertical, Plus, Trash2 } from "lucide-react";
import { SaveBar, type EditorProps } from "@/components/vacancies/vacancy-editors";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { vacanciesApi, type QuestionDraft } from "@/lib/api/vacancies";

type EditorQuestion = QuestionDraft & { clientId: string };

function toDrafts(vacancy: EditorProps["vacancy"]): EditorQuestion[] {
  return vacancy.questions.map(({ position: _position, ...question }) => ({ ...question, clientId: question.id }));
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function QuestionCard({ item, index, open, editable, vacancy, onOpen, onChange, onRemove }: {
  item: EditorQuestion; index: number; open: boolean; editable: boolean; vacancy: EditorProps["vacancy"];
  onOpen: () => void; onChange: (patch: Partial<QuestionDraft>) => void; onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.clientId, disabled: !editable });
  return <article ref={setNodeRef} className="question-item" data-dragging={isDragging} data-expanded={open} style={{ transform: CSS.Transform.toString(transform), transition }}>
    <div className="question-item-heading">
      {editable && <button type="button" className="question-drag" {...attributes} {...listeners} aria-label={`Переместить вопрос ${index + 1}`}><GripVertical size={20} /></button>}
      <span className="question-order">{String(index + 1).padStart(2, "0")}</span>
      <button type="button" className="question-title-button" onClick={onOpen} aria-expanded={open} aria-controls={`question-${item.clientId}`}><span>{item.text || "Новый вопрос"}</span><ChevronDown size={18} /></button>
      {editable && <Button size="icon" variant="ghost" className="question-remove" aria-label={`Удалить вопрос ${index + 1}`} onClick={onRemove}><Trash2 size={17} /></Button>}
    </div>
    {open && <div id={`question-${item.clientId}`} className="question-editor-fields">
      <div className="space-y-2"><Label htmlFor={`text-${item.clientId}`}>Вопрос кандидату</Label><Textarea id={`text-${item.clientId}`} rows={3} value={item.text} disabled={!editable} placeholder="Что вы хотите узнать?" onChange={event => onChange({ text: event.target.value })} /></div>
      <div className="space-y-2"><Label htmlFor={`points-${item.clientId}`}>Что важно услышать</Label><Textarea id={`points-${item.clientId}`} rows={2} value={item.expected_points.join("\n")} disabled={!editable} placeholder="По одному пункту на строку" onChange={event => onChange({ expected_points: event.target.value.split("\n") })} /></div>
      {vacancy.rubric.length > 0 && <fieldset className="question-competencies"><legend>Критерии оценки</legend>{vacancy.rubric.map(competency => <Checkbox key={competency.id} checked={item.competency_ids.includes(competency.id)} disabled={!editable} onCheckedChange={checked => onChange({ competency_ids: checked ? [...item.competency_ids, competency.id] : item.competency_ids.filter(id => id !== competency.id) })}>{competency.name}</Checkbox>)}</fieldset>}
      <details className="question-timing"><summary>Время и попытки<ChevronDown size={16} /></summary><div className="question-timing-fields">
        {([
          ["prep_seconds", "Подготовка, сек", 0, 600, vacancy.settings.prep_seconds],
          ["max_answer_seconds", "Ответ, сек", 30, 900, vacancy.settings.max_answer_seconds],
          ["retakes_allowed", "Перезаписи", 0, 5, vacancy.settings.retakes_allowed],
        ] as const).map(([key, label, min, max, fallback]) => <div key={key} className="space-y-2"><Label htmlFor={`${key}-${item.clientId}`}>{label}</Label><Input id={`${key}-${item.clientId}`} type="number" min={min} max={max} placeholder={String(fallback)} value={item[key] ?? ""} disabled={!editable} onChange={event => onChange({ [key]: optionalNumber(event.target.value) })} /></div>)}
        <Checkbox className="question-followup" checked={item.allows_followup} disabled={!editable} onCheckedChange={checked => onChange({ allows_followup: checked === true })}>Разрешить уточняющий вопрос</Checkbox>
      </div></details>
    </div>}
  </article>;
}

export function QuestionsEditor({ vacancy, editable, onSaved, onError }: EditorProps) {
  const { toast } = useToast();
  const [items, setItems] = useState<EditorQuestion[]>(() => toDrafts(vacancy));
  const [opened, setOpened] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const dirty = JSON.stringify(items) !== JSON.stringify(toDrafts(vacancy));
  const reorder = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    setItems(current => {
      const from = current.findIndex(item => item.clientId === active.id);
      const to = current.findIndex(item => item.clientId === over.id);
      return from < 0 || to < 0 ? current : arrayMove(current, from, to);
    });
  };
  const save = async () => {
    const cleaned = items.map(({ clientId: _clientId, ...item }) => ({ ...item, text: item.text.trim() })).filter(item => item.text);
    setPending(true);
    try {
      const updated = await vacanciesApi.replaceQuestions(vacancy.id, cleaned);
      onSaved(updated); setItems(toDrafts(updated)); toast({ title: "Вопросы сохранены" });
    } catch (error) { onError(error, "Не удалось сохранить вопросы"); }
    finally { setPending(false); }
  };
  const add = () => {
    const question: EditorQuestion = { clientId: crypto.randomUUID(), kind: "video", text: "", expected_points: [], competency_ids: [], allows_followup: false, prep_seconds: null, max_answer_seconds: null, retakes_allowed: null };
    setItems(current => [...current, question]); setOpened(question.clientId);
  };
  return <section className="questions-workspace">
    <div className="questions-toolbar"><div><h2>Сценарий интервью <span>{items.length}</span></h2>{editable && <p>Перетаскивайте вопросы за ручку слева.</p>}</div>{editable && <Button variant="outline" onClick={add} disabled={pending}><Plus size={17} />Добавить</Button>}</div>
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={reorder} accessibility={{ screenReaderInstructions: { draggable: "Нажмите пробел, чтобы взять вопрос. Стрелки меняют порядок. Пробел завершает, Escape отменяет." }, announcements: { onDragStart: () => "Вопрос выбран. Перемещайте стрелками.", onDragOver: ({ over }) => over ? `Позиция ${items.findIndex(item => item.clientId === over.id) + 1}` : undefined, onDragEnd: ({ over }) => over ? `Вопрос перемещён на позицию ${items.findIndex(item => item.clientId === over.id) + 1}` : "Перемещение отменено", onDragCancel: () => "Перемещение отменено" } }}>
      <SortableContext items={items.map(item => item.clientId)} strategy={verticalListSortingStrategy}>
        <div className="questions-list">{items.map((item, index) => <QuestionCard key={item.clientId} item={item} index={index} open={opened === item.clientId} editable={editable && !pending} vacancy={vacancy} onOpen={() => setOpened(opened === item.clientId ? null : item.clientId)} onChange={patch => setItems(current => current.map(question => question.clientId === item.clientId ? { ...question, ...patch } : question))} onRemove={() => setItems(current => current.filter(question => question.clientId !== item.clientId))} />)}</div>
      </SortableContext>
    </DndContext>
    {items.length === 0 && <p className="questions-empty">Добавьте первый вопрос.</p>}
    {editable && <div className="questions-save"><SaveBar pending={pending} dirty={dirty} onSave={save} onReset={() => { setItems(toDrafts(vacancy)); setOpened(null); }} /></div>}
  </section>;
}
