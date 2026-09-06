"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/*
 * Состояние панели ассистента живёт над каркасом приложения: панель пристыкована
 * справа и не перекрывает страницу — контент сдвигается, и предложение ассистента
 * можно сверить с тем, что на экране. Открыть панель с подсказкой может любая
 * страница через событие ``leonit:assistant-open``.
 */

export const ASSISTANT_OPEN_EVENT = "leonit:assistant-open";

export type AssistantOpenDetail = {
  /** Текст, который подставить в поле ввода. */
  prompt?: string;
  /** Отправить подсказку сразу, не дожидаясь пользователя. */
  send?: boolean;
};

/** Открыть ассистента из любого места кабинета (кнопка «Собрать с ИИ» и подобные). */
export function openAssistant(detail: AssistantOpenDetail = {}): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<AssistantOpenDetail>(ASSISTANT_OPEN_EVENT, { detail }));
}

type DockState = {
  open: boolean;
  setOpen: (open: boolean) => void;
  /** Подсказка, пришедшая с последним событием открытия; панель забирает её один раз. */
  pending: AssistantOpenDetail | null;
  takePending: () => AssistantOpenDetail | null;
};

const DockContext = createContext<DockState | null>(null);

export function AssistantDockProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<AssistantOpenDetail | null>(null);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<AssistantOpenDetail>).detail ?? {};
      setPending(detail);
      setOpen(true);
    };
    window.addEventListener(ASSISTANT_OPEN_EVENT, handler);
    return () => window.removeEventListener(ASSISTANT_OPEN_EVENT, handler);
  }, []);

  const takePending = useCallback(() => {
    let taken: AssistantOpenDetail | null = null;
    setPending((current) => {
      taken = current;
      return null;
    });
    return taken;
  }, []);

  const value = useMemo(() => ({ open, setOpen, pending, takePending }), [open, pending, takePending]);
  return <DockContext.Provider value={value}>{children}</DockContext.Provider>;
}

export function useAssistantDock(): DockState {
  const context = useContext(DockContext);
  if (!context) {
    throw new Error("useAssistantDock: нужен AssistantDockProvider");
  }
  return context;
}
