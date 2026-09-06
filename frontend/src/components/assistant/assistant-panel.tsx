"use client";

import Link from "@/lib/router";
import { usePathname } from "@/lib/router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowUpRight,
  Check,
  CheckCircle2,
  History,
  MessageSquare,
  Plus,
  ArrowUp,
  Mic,
  Square,
  Sparkles,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  ActionResult,
  ProposalPreview,
  actionHref,
  proposalButton,
  proposalCaption,
  proposalHref,
  type ActionLink,
} from "@/components/assistant/action-views";
import { useAssistantDock } from "@/components/assistant/dock";
import { LogoGlyph } from "@/components/brand/logo";
import { Skeleton } from "@/components/ui/skeleton";
import { useDictation } from "@/hooks/use-dictation";
import { useAuth } from "@/components/auth/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  assistantApi,
  toolLabel,
  toolProgressLabel,
  type AssistantAction,
  type AssistantMessage,
  type AssistantThread,
  type Proposal,
} from "@/lib/api/assistant";
import { interviewsApi } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";
import { reportsApi, type Decision } from "@/lib/api/reports";
import { vacanciesApi, type QuestionDraft, type RubricCompetency, type VacancyLevel } from "@/lib/api/vacancies";
import { cn } from "@/lib/utils";

/*
 * Ассистент в контексте страницы: панель пристыкована справа и не перекрывает
 * страницу — контент сдвигается (см. AssistantDockProvider), и предложение можно
 * сверить с тем, что на экране. Состояние диалога живёт в компоненте, а не в
 * панели: закрытие не обрывает стрим и не теряет черновик. Крупные и необратимые
 * действия ассистент только предлагает: в карточке видно содержимое, кнопка
 * называет действие и вызывает обычный продуктовый API, а не ручку ассистента.
 */

type Draft = { text: string; actions: AssistantAction[]; running: string[] };

/** Где лежит действие в истории — чтобы отметить подтверждение на сервере. */
type ActionRef = { messageId: string; index: number } | null;

/** Страницы кабинета перечитывают данные после подтверждённого действия. */
export const DATA_CHANGED_EVENT = "leonit:data-changed";

function announceDataChanged(proposal: Proposal): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(DATA_CHANGED_EVENT, { detail: { action: proposal.action, params: proposal.params } }),
  );
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function proposalKey(proposal: Proposal): string {
  return JSON.stringify([proposal.action, proposal.params]);
}

type Executed = { summary: string; link: ActionLink | null };

/** Подтверждение предложения — через продуктовый API соответствующей области. */
async function executeProposal(proposal: Proposal): Promise<Executed> {
  const params = proposal.params as Record<string, never>;
  const link = proposalHref(proposal);
  switch (proposal.action) {
    case "create_vacancy": {
      const vacancy = await vacanciesApi.create({
        title: params.title,
        description: params.description ?? "",
        requirements: params.requirements ?? "",
        skills: (params.skills as string[] | undefined) ?? [],
        level: (params.level as VacancyLevel | null | undefined) ?? null,
      });
      return {
        summary: `Черновик вакансии «${vacancy.title}» создан.`,
        link: { href: `/vacancies/${vacancy.id}`, label: "Открыть вакансию" },
      };
    }
    case "invite": {
      const interview = await interviewsApi.invite({
        vacancy_id: params.vacancy_id,
        full_name: params.full_name,
        email: params.email,
        send_email: params.send_email ?? true,
      });
      return {
        summary: interview.link ? `Приглашение отправлено. Ссылка: ${interview.link}` : "Приглашение отправлено.",
        link: {
          href: `/vacancies/${interview.vacancy_id}/interviews/${interview.id}`,
          label: "Открыть приглашение",
        },
      };
    }
    case "publish":
      await vacanciesApi.publish(params.vacancy_id);
      return { summary: "Вакансия опубликована.", link };
    case "archive":
      await vacanciesApi.archive(params.vacancy_id);
      return { summary: "Вакансия отправлена в архив.", link };
    case "decide":
      await reportsApi.decide(params.interview_id, {
        decision: params.decision as Decision,
        note: params.note ?? "",
      });
      return { summary: "Решение сохранено.", link };
    case "replace_questions":
      await vacanciesApi.replaceQuestions(params.vacancy_id, params.questions as QuestionDraft[]);
      return { summary: "Вопросы вакансии обновлены.", link };
    case "update_rubric":
      await vacanciesApi.update(params.vacancy_id, {
        rubric: params.rubric as RubricCompetency[],
      });
      return { summary: "Рубрика вакансии обновлена.", link };
    default:
      throw new Error(`Неизвестное действие: ${proposal.action}`);
  }
}

function LinkButton({ link }: { link: ActionLink }) {
  return (
    <Button asChild variant="outline" size="sm">
      <Link href={link.href}>
        {link.label}
        <ArrowUpRight className="ml-1 h-3.5 w-3.5" />
      </Link>
    </Button>
  );
}

function ActionCard({
  action,
  confirmed,
  confirmedLink,
  dismissed,
  onConfirm,
  onDismiss,
  actionRef,
}: {
  action: AssistantAction;
  confirmed: boolean;
  confirmedLink: ActionLink | null;
  dismissed: boolean;
  onConfirm?: (proposal: Proposal, ref: ActionRef) => Promise<void>;
  onDismiss?: (proposal: Proposal) => void;
  actionRef: ActionRef;
}) {
  const [pending, setPending] = useState(false);
  const proposal = action.kind === "proposed" ? action.proposal : null;
  const doneLink = actionHref(action);
  const icon =
    action.kind === "error" ? (
      <AlertCircle className="h-4 w-4 text-destructive" />
    ) : action.kind === "proposed" ? (
      <Sparkles className="h-4 w-4 text-accent" />
    ) : (
      <CheckCircle2 className="h-4 w-4 text-accent" />
    );
  const button = proposal ? proposalButton(proposal) : null;
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-3 text-sm",
        action.kind === "error" && "border-destructive/40",
        action.kind === "proposed" && !dismissed && "border-accent/40",
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0">{icon}</span>
        <div className="min-w-0 flex-1">
          <span className="font-medium">{toolLabel(action.tool)}</span>
          {action.summary ? (
            <p className={cn("mt-1 text-muted-foreground", action.kind === "error" && "text-destructive")}>
              {action.summary}
            </p>
          ) : null}
        </div>
      </div>
      {proposal && button ? (
        <div className={cn("mt-3 rounded-md p-3", dismissed ? "bg-secondary/60" : "bg-accent-soft")}>
          <p className="text-sm">{proposal.summary}</p>
          <div className="mt-2">
            <ProposalPreview proposal={proposal} result={action.result} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {confirmed ? (
              <>
                <Badge className="gap-1">
                  <Check className="h-3 w-3" /> Выполнено
                </Badge>
                {confirmedLink ? <LinkButton link={confirmedLink} /> : null}
              </>
            ) : dismissed ? (
              <Badge variant="secondary">Отклонено</Badge>
            ) : (
              <>
                <Button
                  size="sm"
                  variant={button.destructive ? "destructive" : "default"}
                  disabled={pending || !onConfirm}
                  onClick={async () => {
                    if (!onConfirm) return;
                    setPending(true);
                    try {
                      await onConfirm(proposal, actionRef);
                    } finally {
                      setPending(false);
                    }
                  }}
                >
                  {pending ? <Skeleton className="h-4 w-4 rounded-md" /> : <Check className="h-4 w-4" />}
                  {button.label}
                </Button>
                <Button size="sm" variant="ghost" disabled={pending || !onDismiss} onClick={() => onDismiss?.(proposal)}>
                  Отклонить
                </Button>
              </>
            )}
          </div>
          {!confirmed && !dismissed ? (
            <p className="mt-2 text-xs text-muted-foreground">{proposalCaption(proposal)}</p>
          ) : null}
        </div>
      ) : null}
      <ActionResult action={action} />
      {doneLink ? (
        <div className="mt-2">
          <LinkButton link={doneLink} />
        </div>
      ) : null}
    </div>
  );
}

function AssistantBubble({ children, role }: { children: React.ReactNode; role: "user" | "assistant" }) {
  return (
    <div className={cn("flex", role === "user" ? "justify-end" : "justify-start")}>
      <div className="assistant-bubble" data-role={role}>
        {children}
      </div>
    </div>
  );
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="assistant-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function formatWhen(value: string): string {
  return new Date(value).toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function AssistantDock() {
  const pathname = usePathname();
  const { toast } = useToast();
  const { open, setOpen, pending: pendingOpen, takePending } = useAssistantDock();
  const [view, setView] = useState<"chat" | "threads">("chat");
  const [threads, setThreads] = useState<AssistantThread[] | null>(null);
  const [placeholders, setPlaceholders] = useState<string[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const dictation = useDictation(input, setInput);
  const [confirmed, setConfirmed] = useState<Map<string, ActionLink | null>>(() => new Map());
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sendRef = useRef<(text: string) => Promise<void>>(async () => undefined);

  // Справочники — один раз при первом открытии.
  useEffect(() => {
    if (!open || threads !== null) return;
    assistantApi
      .threads()
      .then(setThreads)
      .catch(() => setThreads([]));
    assistantApi
      .placeholders()
      .then((data) => setPlaceholders(data.items))
      .catch(() => setPlaceholders([]));
  }, [open, threads]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, draft, view, open, loadingMessages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Панель открыли с подсказкой (кнопка «Собрать с ИИ»): подставляем или сразу отправляем.
  useEffect(() => {
    if (!open || !pendingOpen) return;
    const detail = takePending();
    if (!detail?.prompt) return;
    setView("chat");
    if (detail.send) {
      void sendRef.current(detail.prompt);
    } else {
      setInput(detail.prompt);
      window.setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open, pendingOpen, takePending]);

  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, setOpen]);

  const visibleMessages = useMemo(
    () => messages.filter((message) => message.role !== "tool"),
    [messages],
  );

  const selectThread = useCallback(async (id: string) => {
    setThreadId(id);
    setView("chat");
    setDraft(null);
    setLoadingMessages(true);
    try {
      setMessages(await assistantApi.messages(id));
    } catch {
      setMessages([]);
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  const newChat = () => {
    abortRef.current?.abort();
    setThreadId(null);
    setMessages([]);
    setDraft(null);
    setStreaming(false);
    setView("chat");
  };

  const archive = async (id: string) => {
    try {
      await assistantApi.archiveThread(id);
      setThreads((items) => (items ?? []).filter((item) => item.id !== id));
      if (threadId === id) newChat();
    } catch (error) {
      toast({ variant: "destructive", title: errorMessage(error, "Не удалось удалить чат") });
    }
  };

  const touchThread = (thread: { id: string; title: string }) =>
    setThreads((items) =>
      (items ?? []).map((item) =>
        item.id === thread.id ? { ...item, title: thread.title, updated_at: new Date().toISOString() } : item,
      ),
    );

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || streaming) return;
    setInput("");
    setStreaming(true);
    setView("chat");
    const optimistic: AssistantMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
      actions: [],
      created_at: new Date().toISOString(),
    };
    setMessages((items) => [...items, optimistic]);
    setDraft({ text: "", actions: [], running: [] });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      let id = threadId;
      if (!id) {
        const thread = await assistantApi.createThread({ page_path: pathname });
        id = thread.id;
        setThreadId(id);
        setThreads((items) => [thread, ...(items ?? [])]);
      }
      await assistantApi.stream(
        id,
        { content, page_path: pathname },
        (event) => {
          switch (event.type) {
            case "user":
              setMessages((items) =>
                items.map((item) => (item.id === optimistic.id ? event.data.message : item)),
              );
              break;
            case "token":
              setDraft((current) => ({
                text: (current?.text ?? "") + event.data.text,
                actions: current?.actions ?? [],
                running: current?.running ?? [],
              }));
              break;
            case "reset":
              setDraft((current) => ({
                text: "",
                actions: current?.actions ?? [],
                running: current?.running ?? [],
              }));
              break;
            case "tool_start":
              setDraft((current) => ({
                text: current?.text ?? "",
                actions: current?.actions ?? [],
                running: [...(current?.running ?? []), event.data.tool],
              }));
              break;
            case "action":
              setDraft((current) => {
                const running = [...(current?.running ?? [])];
                const position = running.indexOf(event.data.tool);
                if (position !== -1) running.splice(position, 1);
                return {
                  text: current?.text ?? "",
                  actions: [...(current?.actions ?? []), event.data],
                  running,
                };
              });
              break;
            case "done": {
              const saved = event.data.message;
              setMessages((items) => [...items, saved]);
              setDraft(null);
              touchThread(event.data.thread);
              // Предложение могли подтвердить, пока оно ещё было в черновике стрима:
              // отметку на сервере ставим по сохранённому сообщению.
              saved.actions.forEach((action, index) => {
                if (action.proposal && !action.confirmed_at && confirmed.has(proposalKey(action.proposal))) {
                  void assistantApi.confirmAction(id as string, saved.id, index).catch(() => undefined);
                }
              });
              break;
            }
            case "error": {
              // Ход прерван: черновик стрима отбрасываем, а сохранённое сообщение
              // с причиной показываем как обычный ответ — оно есть и в истории.
              const failed = event.data.message;
              if (failed) setMessages((items) => [...items, failed]);
              if (event.data.thread) touchThread(event.data.thread);
              setDraft(null);
              toast({ variant: "destructive", title: event.data.detail });
              break;
            }
          }
        },
        controller.signal,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setDraft(null);
        toast({ variant: "destructive", title: errorMessage(error, "Ассистент недоступен") });
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setStreaming(false);
    }
  };
  sendRef.current = send;

  const confirm = async (proposal: Proposal, ref: ActionRef) => {
    try {
      const executed = await executeProposal(proposal);
      setConfirmed((links) => new Map(links).set(proposalKey(proposal), executed.link));
      announceDataChanged(proposal);
      toast({ title: "Готово", description: executed.summary });
      if (ref && threadId) {
        // Отметка хранится в сообщении: после перезагрузки кнопка не вернётся.
        const updated = await assistantApi.confirmAction(threadId, ref.messageId, ref.index).catch(() => null);
        if (updated) setMessages((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      }
    } catch (error) {
      toast({ variant: "destructive", title: errorMessage(error, "Не удалось выполнить действие") });
    }
  };

  const dismiss = (proposal: Proposal) => {
    setDismissed((keys) => new Set(keys).add(proposalKey(proposal)));
  };

  const activeThread = threads?.find((item) => item.id === threadId) ?? null;

  const renderActions = (actions: AssistantAction[], prefix: string, messageId: string | null) =>
    actions.length ? (
      <div className="space-y-2">
        {actions.map((action, index) => {
          const key = action.proposal ? proposalKey(action.proposal) : null;
          const isConfirmed = Boolean(action.confirmed_at || (key && confirmed.has(key)));
          const link = key && confirmed.has(key) ? (confirmed.get(key) ?? null) : action.proposal ? proposalHref(action.proposal) : null;
          return (
            <ActionCard
              key={`${prefix}-${index}`}
              action={action}
              confirmed={isConfirmed}
              confirmedLink={link}
              dismissed={Boolean(key && dismissed.has(key))}
              onConfirm={confirm}
              onDismiss={dismiss}
              actionRef={messageId ? { messageId, index } : null}
            />
          );
        })}
      </div>
    ) : null;

  return (
    <>
        <aside
          role="complementary"
          aria-label="Ассистент"
          className="assistant-panel"
          data-open={open}
          aria-hidden={!open}
          inert={!open}
        >
          <div className="assistant-header">
            {view === "threads" ? (
              <Button variant="ghost" size="icon" onClick={() => setView("chat")} aria-label="Назад к чату">
                <ArrowLeft className="h-4 w-4" />
              </Button>
            ) : (
              <Button variant="ghost" size="icon" onClick={() => setView("threads")} aria-label="История чатов">
                <History className="h-4 w-4" />
              </Button>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-base font-semibold">
                {view === "threads" ? "История чатов" : activeThread?.title || "Леон"}
              </h2>

            </div>
            <Button variant="ghost" size="icon" onClick={newChat} aria-label="Новый чат" title="Новый чат">
              <Plus className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Закрыть ассистента">
              <X className="h-4 w-4" />
            </Button>
          </div>

          {view === "threads" ? (
            <div className="thin-scrollbar flex-1 overflow-y-auto p-2">
              {threads === null ? (
                <div className="space-y-3 p-3" aria-label="Загрузка чатов"><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-3/4" /></div>
              ) : threads.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">Чатов пока нет.</p>
              ) : (
                <ul className="space-y-1">
                  {threads.map((thread) => (
                    <li key={thread.id} className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => void selectThread(thread.id)}
                        className={cn(
                          "flex min-w-0 flex-1 flex-col rounded-lg px-3 py-2 text-left hover:bg-accent-soft",
                          thread.id === threadId && "bg-accent-soft",
                        )}
                      >
                        <span className="flex items-center gap-2 text-sm font-medium">
                          <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate">{thread.title || "Новый чат"}</span>
                        </span>
                        <span className="text-xs text-muted-foreground">{formatWhen(thread.updated_at)}</span>
                      </button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Удалить чат"
                        onClick={() => void archive(thread.id)}
                      >
                        <Trash2 className="h-4 w-4 text-muted-foreground" />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="assistant-messages thin-scrollbar">
              {loadingMessages ? (
                <div className="space-y-4" aria-label="Загрузка сообщений"><Skeleton className="ml-auto h-16 w-3/4" /><Skeleton className="h-28 w-full" /></div>
              ) : visibleMessages.length === 0 && !draft ? (
                <div className="assistant-empty">
                  <LogoGlyph shimmer className="assistant-empty-logo" />
                  <p className="mt-5 text-center text-lg font-extrabold">Привет! Что сделаем?</p>
                  <p className="mt-1 text-center text-sm text-muted-foreground">
                    Вопросы, вакансии, отчёты — я рядом.
                  </p>
                  <ul className="assistant-suggestions">
                    {placeholders.map((item) => (
                      <li key={item}>
                        <button
                          type="button"
                          onClick={() => void send(item)}
                          disabled={streaming}
                          className="disabled:opacity-50"
                        >
                          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                          <span>{item}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="space-y-4">
                  {visibleMessages.map((message) =>
                    message.role === "user" ? (
                      <AssistantBubble key={message.id} role="user">
                        <span className="whitespace-pre-wrap">{message.content}</span>
                      </AssistantBubble>
                    ) : (
                      <div key={message.id} className="space-y-2">
                        {renderActions(message.actions, message.id, message.id)}
                        {message.content ? (
                          <AssistantBubble role="assistant">
                            <Markdown text={message.content} />
                          </AssistantBubble>
                        ) : null}
                      </div>
                    ),
                  )}
                  {draft ? (
                    <div className="space-y-2">
                      {renderActions(draft.actions, "draft", null)}
                      {draft.text ? (
                        <AssistantBubble role="assistant">
                          <Markdown text={draft.text} />
                        </AssistantBubble>
                      ) : (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
                          {draft.running.length ? (
                            <>
                              <Skeleton className="h-3.5 w-3.5 rounded-md" />
                              {toolProgressLabel(draft.running[draft.running.length - 1])}
                            </>
                          ) : (
                            <>
                              <Wrench className="h-3.5 w-3.5 animate-pulse" />
                              {draft.actions.length ? "Ассистент обрабатывает результаты…" : "Ассистент думает…"}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  ) : null}
                  <div ref={bottomRef} />
                </div>
              )}
            </div>
          )}

          {view === "chat" ? (
            <form className="assistant-composer" onSubmit={event => { event.preventDefault(); dictation.stop(); void send(input); }}>
              <div className="assistant-composer-input">
                <Textarea ref={inputRef} value={input} onChange={event => setInput(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault(); dictation.stop(); void send(input);
                    }
                  }} rows={4} maxLength={8000} placeholder="Спросите что-нибудь…" aria-label="Сообщение ассистенту" />
                {input.length > 0 && <span className="assistant-counter">{input.length.toLocaleString("ru-RU")} / 8 000</span>}
              </div>
              <div className="assistant-composer-footer">
                <span className="assistant-composer-hint">Shift + Enter — новая строка</span>
                <div className="assistant-composer-actions">
                  <Button variant="ghost" size="icon" type="button" onClick={dictation.toggle} disabled={!dictation.supported || streaming}
                    aria-label={dictation.listening ? "Остановить голосовой ввод" : "Ввести голосом"} aria-pressed={dictation.listening}
                    title={dictation.supported ? "Ввести голосом" : "Голосовой ввод недоступен в этом браузере"}><Mic size={17} /></Button>
                  {streaming ? <Button type="button" variant="secondary" size="icon" aria-label="Остановить ответ" onClick={() => {
                    abortRef.current?.abort();
                    if (draft?.text) setMessages(items => [...items, { id: `stopped-${Date.now()}`, role: "assistant", content: draft.text, actions: draft.actions, created_at: new Date().toISOString() }]);
                    setDraft(null); setStreaming(false);
                  }}><Square size={14} fill="currentColor" /></Button> :
                    <Button className="assistant-send" type="submit" size="sm" disabled={!input.trim() || loadingMessages} aria-label="Отправить"><kbd>Enter</kbd><ArrowUp size={18} /></Button>}
                </div>
              </div>
              {dictation.error && <p className="assistant-speech-error" role="alert">{dictation.error}</p>}
            </form>
          ) : null}
        </aside>
    </>
  );
}

export function AssistantPanel() {
  const { can } = useAuth();
  if (!can("assistant.use")) return null;
  return <AssistantDock />;
}

export function AssistantTrigger() {
  const { can } = useAuth();
  const { open, setOpen } = useAssistantDock();
  if (open || !can("assistant.use")) return null;
  return <Button variant="outline" size="sm" className="assistant-trigger" onClick={() => setOpen(true)} aria-label="Спросить Леона"><Sparkles size={17} className="text-primary" /><span>Спросить Леона</span></Button>;
}
