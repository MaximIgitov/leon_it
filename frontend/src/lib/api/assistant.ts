/*
 * Клиент ассистента: треды, сообщения и SSE-стрим ответа.
 *
 * Стрим читается через fetch + ReadableStream, а не EventSource: последний не
 * умеет POST и bearer-заголовок. События приходят блоками `event: …\ndata: …`,
 * разделёнными пустой строкой; парсер накапливает буфер и разбирает готовые блоки.
 */

import { API_BASE_URL, ApiError, apiFetch, getAccessToken } from "./client";

export type ActionKind = "done" | "proposed" | "error";

export type ProposalAction =
  | "create_vacancy"
  | "invite"
  | "publish"
  | "archive"
  | "decide"
  | "replace_questions"
  | "update_rubric";

export type Proposal = {
  action: ProposalAction | string;
  params: Record<string, unknown>;
  summary: string;
};

export type AssistantAction = {
  kind: ActionKind;
  tool: string;
  params: Record<string, unknown>;
  summary: string;
  result: unknown;
  proposal: Proposal | null;
  /** Когда предложение подтвердили кнопкой — хранится в сообщении. */
  confirmed_at?: string | null;
};

export type AssistantThread = {
  id: string;
  title: string;
  page_path: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type AssistantMessage = {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  actions: AssistantAction[];
  created_at: string;
};

export type SendResult = {
  thread: AssistantThread;
  user_message: AssistantMessage;
  assistant_message: AssistantMessage;
};

export type Placeholders = { role: string; items: string[] };

export type StreamEvent =
  | { type: "user"; data: { message: AssistantMessage } }
  | { type: "token"; data: { text: string } }
  /* Инструмент начал работу: генерация идёт десятки секунд, показываем чем занят. */
  | { type: "tool_start"; data: { tool: string; params: Record<string, unknown> } }
  | { type: "action"; data: AssistantAction }
  | { type: "reset"; data: Record<string, never> }
  | { type: "done"; data: { message: AssistantMessage; thread: { id: string; title: string } } }
  /* Ход прерван: причина, сохранённое сообщение ассистента (если ход дошёл до
   * записи) и тред — заголовок уже присвоен первым сообщением. */
  | {
      type: "error";
      data: { detail: string; message?: AssistantMessage; thread?: { id: string; title: string } };
    };

export const TOOL_LABELS: Record<string, string> = {
  list_vacancies: "Список вакансий",
  get_vacancy: "Вакансия",
  create_vacancy: "Создание вакансии",
  generate_questions: "Генерация вопросов",
  review_questions: "Вычитка вопросов",
  generate_rubric: "Рубрика компетенций",
  list_candidates: "Список кандидатов",
  get_candidate: "Карточка кандидата",
  get_interview: "Отчёт по интервью",
  vacancy_summary: "Срез по вакансии",
  ranking: "Рейтинг кандидатов",
  invite_candidate: "Приглашение кандидата",
  publish_vacancy: "Публикация вакансии",
  archive_vacancy: "Архив вакансии",
  decide_candidate: "Решение по кандидату",
  list_members: "Участники организации",
  check_models: "Проверка моделей",
  search_knowledge: "Поиск по базе знаний",
};

/** Что ассистент делает прямо сейчас — для индикатора хода. */
export function toolProgressLabel(tool: string): string {
  const labels: Record<string, string> = {
    generate_rubric: "Составляю рубрику компетенций…",
    generate_questions: "Придумываю вопросы…",
    review_questions: "Вычитываю вопросы…",
    create_vacancy: "Создаю черновик вакансии…",
    vacancy_summary: "Собираю срез по вакансии…",
    ranking: "Смотрю рейтинг…",
    get_interview: "Читаю отчёт по интервью…",
    search_knowledge: "Ищу в базе знаний…",
    check_models: "Проверяю модели…",
  };
  return labels[tool] ?? `${toolLabel(tool)}…`;
}

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}

/** Разбирает один SSE-блок (`event: …\ndata: …`). Неизвестные типы — пропускаем. */
export function parseSseBlock(block: string): StreamEvent | null {
  let type: string | null = null;
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (!type || dataLines.length === 0) return null;
  try {
    return { type, data: JSON.parse(dataLines.join("\n")) } as StreamEvent;
  } catch {
    return null;
  }
}

export async function streamAssistantMessage(
  threadId: string,
  body: { content: string; page_path?: string | null },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Content-Type": "application/json",
  };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${API_BASE_URL}/assistant/threads/${threadId}/messages/stream`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      const payload = await response.json();
      detail = payload?.detail ?? payload;
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(response.status, detail, response.headers.get("x-request-id"));
  }
  if (!response.body) throw new ApiError(response.status, "Пустой поток ответа", null);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const flush = (chunk: string) => {
    buffer += chunk;
    let index = buffer.indexOf("\n\n");
    while (index !== -1) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const event = parseSseBlock(block);
      if (event) onEvent(event);
      index = buffer.indexOf("\n\n");
    }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    flush(decoder.decode(value, { stream: true }));
  }
  flush(decoder.decode());
  if (buffer.trim()) {
    const event = parseSseBlock(buffer);
    if (event) onEvent(event);
  }
}

export const assistantApi = {
  placeholders: () => apiFetch<Placeholders>("/assistant/placeholders"),
  threads: () => apiFetch<AssistantThread[]>("/assistant/threads"),
  createThread: (body: { title?: string; page_path?: string | null }) =>
    apiFetch<AssistantThread>("/assistant/threads", { method: "POST", body }),
  archiveThread: (id: string) => apiFetch<void>(`/assistant/threads/${id}`, { method: "DELETE" }),
  messages: (id: string) => apiFetch<AssistantMessage[]>(`/assistant/threads/${id}/messages`),
  send: (id: string, body: { content: string; page_path?: string | null }) =>
    apiFetch<SendResult>(`/assistant/threads/${id}/messages`, { method: "POST", body }),
  confirmAction: (threadId: string, messageId: string, index: number) =>
    apiFetch<AssistantMessage>(
      `/assistant/threads/${threadId}/messages/${messageId}/actions/${index}/confirm`,
      { method: "POST" },
    ),
  stream: streamAssistantMessage,
};
