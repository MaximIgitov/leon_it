"use client";

import { Skeleton } from "@/components/ui/skeleton";

import { useEffect, useMemo, useRef, useState } from "react";
import { Play, Send } from "lucide-react";

import { RunResultView } from "@/components/reports/code-submission";
import { Button } from "@/components/ui/button";
import type { CodeRunResult } from "@/lib/api/room";
import { formatBytes, languageLabel } from "@/lib/code";
import { cn } from "@/lib/utils";

/*
 * Редактор кода без внешних зависимостей: textarea с моноширинным шрифтом,
 * номерами строк, Tab-отступом, счётчиком байт и автосохранением черновика в
 * localStorage. Подсветка синтаксиса и полноценный редактор (Monaco/CodeMirror)
 * — задел: когда появится раннер, их можно подключить, не меняя контракт ручек.
 */

export const INDENT = "  ";

export type CodeDraft = { language: string; source: string };
export type StoredDraft = CodeDraft & { savedAt: number };
export type Selection = { value: string; selectionStart: number; selectionEnd: number };

export function utf8Length(text: string): number {
  return new TextEncoder().encode(text).length;
}

/**
 * Tab в редакторе: без выделения — вставить отступ, с многострочным выделением —
 * сдвинуть все строки; Shift+Tab — убрать до двух пробелов в начале строк.
 */
export function applyTab(value: string, start: number, end: number, shift = false): Selection {
  const multiline = start !== end && value.slice(start, end).includes("\n");
  if (!shift && !multiline) {
    const next = value.slice(0, start) + INDENT + value.slice(end);
    const cursor = start + INDENT.length;
    return { value: next, selectionStart: cursor, selectionEnd: cursor };
  }
  const blockStart = value.lastIndexOf("\n", start - 1) + 1;
  // Выделение до границы строки не захватывает следующую (пустую) строку.
  const effectiveEnd = multiline && value[end - 1] === "\n" ? end - 1 : end;
  const newlineAfter = value.indexOf("\n", effectiveEnd);
  const blockEnd = newlineAfter === -1 ? value.length : newlineAfter;
  const lines = value.slice(blockStart, blockEnd).split("\n");
  let firstDelta = 0;
  let totalDelta = 0;
  const changed = lines.map((line, index) => {
    let next = line;
    let delta = 0;
    if (shift) {
      const spaces = Math.min(INDENT.length, line.length - line.trimStart().length);
      next = line.slice(spaces);
      delta = -spaces;
    } else {
      next = INDENT + line;
      delta = INDENT.length;
    }
    if (index === 0) firstDelta = delta;
    totalDelta += delta;
    return next;
  });
  const nextValue = value.slice(0, blockStart) + changed.join("\n") + value.slice(blockEnd);
  const selectionStart = Math.max(blockStart, start + firstDelta);
  const selectionEnd = Math.max(selectionStart, end + totalDelta);
  return { value: nextValue, selectionStart, selectionEnd };
}

export function draftStorageKey(token: string, questionId: string): string {
  return `leonit.code.${token.slice(0, 16)}.${questionId}`;
}

export function readDraft(key: string): StoredDraft | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredDraft>;
    if (typeof parsed.source !== "string" || typeof parsed.language !== "string") return null;
    return { language: parsed.language, source: parsed.source, savedAt: Number(parsed.savedAt) || 0 };
  } catch {
    return null;
  }
}

export function writeDraft(key: string, draft: CodeDraft): void {
  try {
    window.localStorage.setItem(key, JSON.stringify({ ...draft, savedAt: Date.now() } satisfies StoredDraft));
  } catch {
    /* приватный режим или переполнение — черновик живёт только в памяти */
  }
}

export function clearDraft(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export type CodeEditorProps = {
  storageKey: string;
  languages: string[];
  maxBytes: number;
  runnerEnabled: boolean;
  /** Черновик или отправленный код с сервера (восстановление после перезагрузки). */
  initial: CodeDraft | null;
  submittedAt: string | null;
  runResult: CodeRunResult | null;
  busy: "submit" | "run" | null;
  error?: string | null;
  onSubmit: (draft: CodeDraft) => void;
  onRun: (draft: CodeDraft) => void;
  onChange?: (draft: CodeDraft) => void;
};

export function CodeEditor({
  storageKey,
  languages,
  maxBytes,
  runnerEnabled,
  initial,
  submittedAt,
  runResult,
  busy,
  error,
  onSubmit,
  onRun,
  onChange,
}: CodeEditorProps) {
  const [language, setLanguage] = useState(() => initial?.language ?? languages[0] ?? "python");
  const [source, setSource] = useState(() => initial?.source ?? "");
  const [dirty, setDirty] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const gutterRef = useRef<HTMLPreElement | null>(null);
  const pendingSelection = useRef<Selection | null>(null);

  // Локальный черновик новее серверного (пишется на каждое нажатие), но
  // отправленный код важнее: после отправки редактор показывает то, что ушло.
  useEffect(() => {
    if (submittedAt) return;
    const local = readDraft(storageKey);
    if (local && (local.source !== initial?.source || local.language !== initial?.language)) {
      setLanguage(languages.includes(local.language) ? local.language : languages[0] ?? "python");
      setSource(local.source);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  useEffect(() => {
    if (submittedAt) setDirty(false);
  }, [submittedAt]);

  useEffect(() => {
    const selection = pendingSelection.current;
    const element = textareaRef.current;
    if (selection && element) {
      element.selectionStart = selection.selectionStart;
      element.selectionEnd = selection.selectionEnd;
      pendingSelection.current = null;
    }
  }, [source]);

  const bytes = useMemo(() => utf8Length(source), [source]);
  const lines = useMemo(() => source.split("\n").length, [source]);
  const overLimit = bytes > maxBytes;
  const empty = source.trim().length === 0;
  const draft: CodeDraft = { language, source };

  const update = (nextSource: string, nextLanguage = language) => {
    setSource(nextSource);
    setLanguage(nextLanguage);
    setDirty(true);
    writeDraft(storageKey, { language: nextLanguage, source: nextSource });
    onChange?.({ language: nextLanguage, source: nextSource });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Tab") return;
    event.preventDefault();
    const element = event.currentTarget;
    const next = applyTab(element.value, element.selectionStart, element.selectionEnd, event.shiftKey);
    pendingSelection.current = next;
    update(next.value);
  };

  const submittedLabel = submittedAt
    ? `Код отправлен в ${new Date(submittedAt).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}.`
    : null;

  return (
    <div className="space-y-3" data-testid="code-editor">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Язык</span>
          <select
            value={language}
            onChange={(event) => update(source, event.target.value)}
            aria-label="Язык программирования"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {languages.map((item) => (
              <option key={item} value={item}>
                {languageLabel(item)}
              </option>
            ))}
          </select>
        </label>
        <span
          className={cn("text-xs tabular-nums", overLimit ? "font-medium text-destructive" : "text-muted-foreground")}
          aria-live="polite"
        >
          {formatBytes(bytes)} / {formatBytes(maxBytes)} · {lines} стр.
        </span>
      </div>

      <div className="flex overflow-hidden rounded-lg border bg-background focus-within:ring-2 focus-within:ring-ring">
        <pre
          ref={gutterRef}
          aria-hidden
          className="select-none overflow-hidden bg-secondary/40 px-2 py-3 text-right font-mono text-xs leading-5 text-muted-foreground"
        >
          {Array.from({ length: lines }, (_, index) => index + 1).join("\n")}
        </pre>
        <textarea
          ref={textareaRef}
          value={source}
          onChange={(event) => update(event.target.value)}
          onKeyDown={onKeyDown}
          onScroll={(event) => {
            if (gutterRef.current) gutterRef.current.scrollTop = event.currentTarget.scrollTop;
          }}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          autoComplete="off"
          wrap="off"
          placeholder="// Напишите решение здесь. Tab — отступ, Shift+Tab — убрать отступ."
          aria-label="Редактор кода"
          className="thin-scrollbar min-h-[280px] flex-1 resize-y whitespace-pre bg-transparent px-3 py-3 font-mono text-xs leading-5 outline-none placeholder:text-muted-foreground"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => onSubmit(draft)} disabled={empty || overLimit || busy !== null}>
          {busy === "submit" ? <Skeleton className="h-4 w-4 rounded-md" /> : <Send />}
          {submittedAt && !dirty ? "Отправить снова" : "Отправить код"}
        </Button>
        <Button
          variant="outline"
          onClick={() => onRun(draft)}
          disabled={!runnerEnabled || empty || overLimit || busy !== null}
          title={runnerEnabled ? undefined : "Запуск кода появится позже"}
          aria-describedby={runnerEnabled ? undefined : "code-runner-hint"}
        >
          {busy === "run" ? <Skeleton className="h-4 w-4 rounded-md" /> : <Play />}
          Запустить
        </Button>
        {!runnerEnabled ? (
          <span id="code-runner-hint" className="text-xs text-muted-foreground">
            Запуск кода появится позже
          </span>
        ) : null}
      </div>

      {overLimit ? (
        <p className="text-sm text-destructive" role="alert">
          Код превышает лимит {formatBytes(maxBytes)} — сократите решение.
        </p>
      ) : null}
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {submittedLabel ? (
        <p className={cn("text-sm", dirty ? "text-warning" : "text-success")}>
          {dirty ? "Код изменён после отправки — отправьте снова, чтобы сохранить правки." : submittedLabel}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">Черновик сохраняется автоматически в этом браузере.</p>
      )}
      {runResult ? <RunResultView result={runResult} /> : null}
    </div>
  );
}
