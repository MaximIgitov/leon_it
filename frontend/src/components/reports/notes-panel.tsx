"use client";

import { Skeleton } from "@/components/ui/skeleton";

import { useState } from "react";
import { MessageSquarePlus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Note } from "@/lib/api/reports";

function formatAt(seconds: number | null): string {
  if (seconds === null) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function NotesPanel({
  notes,
  canWrite,
  currentUserId,
  onAdd,
  onDelete,
  onSeek,
}: {
  notes: Note[];
  canWrite: boolean;
  currentUserId?: string | null;
  onAdd: (text: string) => Promise<void | boolean>;
  onDelete?: (noteId: string) => Promise<void>;
  onSeek?: (answerId: string, seconds: number | null) => void;
}) {
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);

  const submit = async () => {
    if (!draft.trim()) return;
    setPending(true);
    try {
      const saved = await onAdd(draft.trim());
      if (saved !== false) setDraft("");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card className="report-notes-panel rounded-[22px] border">
      <CardHeader>
        <CardTitle className="text-xl">Заметки команды</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {notes.length === 0 ? (
          <p className="text-sm text-muted-foreground">Пока нет заметок.</p>
        ) : (
          <ul className="space-y-2">
            {notes.map((note) => (
              <li key={note.id} className="report-note">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="report-note-author">
                      {note.author_label} · {new Date(note.created_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}
                      {note.answer_id && note.at_s !== null ? (
                        <button
                          type="button"
                          className="ml-2 text-primary hover:underline"
                          onClick={() => onSeek?.(note.answer_id!, note.at_s)}
                        >
                          {formatAt(note.at_s)}
                        </button>
                      ) : null}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap">{note.text}</p>
                  </div>
                  {canWrite && onDelete && note.author_user_id && note.author_user_id === currentUserId ? (
                    <Button variant="ghost" size="icon" aria-label="Удалить заметку" onClick={() => onDelete(note.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
        {canWrite ? (
          <div className="space-y-2">
            <Label htmlFor="report-note">Новая заметка</Label>
            <Textarea id="report-note" rows={4} disabled={pending} placeholder="Наблюдения и вопросы для команды" value={draft} onChange={(e) => setDraft(e.target.value)} />
            <Button size="sm" onClick={submit} disabled={pending || !draft.trim()}>
              {pending ? <Skeleton className="mr-2 h-4 w-4 rounded-md" /> : <MessageSquarePlus className="mr-2 h-4 w-4" />}
              Добавить заметку
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
