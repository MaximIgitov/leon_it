import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { parseSseBlock, streamAssistantMessage, type StreamEvent } from "./assistant";

/*
 * Стрим ассистента: события user/token/action/reset/done/error. Здесь проверяем
 * разбор SSE-блоков и то, что клиент отдаёт события в порядке прихода — в том
 * числе `reset` (черновик отброшен) и `error` (ход прерван, но сообщение с
 * причиной сохранено), которые панель обрабатывает отдельно от `done`.
 */

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("parseSseBlock", () => {
  it("разбирает event и data, терпит CRLF и пробел после двоеточия", () => {
    expect(parseSseBlock('event: token\r\ndata: {"text":"Прив"}')).toEqual({
      type: "token",
      data: { text: "Прив" },
    });
    expect(parseSseBlock("event:reset\ndata:{}")).toEqual({ type: "reset", data: {} });
  });

  it("возвращает null для неполного блока и невалидного JSON", () => {
    expect(parseSseBlock("data: {}")).toBeNull();
    expect(parseSseBlock("event: token")).toBeNull();
    expect(parseSseBlock("event: token\ndata: {not json")).toBeNull();
  });

  it("собирает многострочный data", () => {
    expect(parseSseBlock('event: token\ndata: {"text":\ndata: "x"}')).toEqual({
      type: "token",
      data: { text: "x" },
    });
  });
});

describe("streamAssistantMessage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("отдаёт события по мере прихода, включая reset и error", async () => {
    const message = { id: "m1", role: "assistant", content: "Сбой", actions: [], created_at: "2026-09-03T00:00:00Z" };
    const chunks = [
      'event: user\ndata: {"message":{"id":"u1","role":"user","content":"Привет","actions":[],"created_at":"2026-09-03T00:00:00Z"}}\n\n',
      'event: token\ndata: {"text":"Сейчас "}\n\nevent: tok',
      'en\ndata: {"text":"посмотрю"}\n\nevent: reset\ndata: {}\n\n',
      'event: action\ndata: {"kind":"done","tool":"list_vacancies","params":{},"summary":"Найдено: 1","result":[],"proposal":null}\n\n',
      `event: error\ndata: ${JSON.stringify({ detail: "Не удалось получить ответ модели", message })}\n\n`,
    ];
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse(chunks)));

    const events: StreamEvent[] = [];
    await streamAssistantMessage("t1", { content: "Привет", page_path: "/vacancies" }, (event) => events.push(event));

    expect(events.map((event) => event.type)).toEqual(["user", "token", "token", "reset", "action", "error"]);
    const error = events.at(-1);
    expect(error?.type).toBe("error");
    if (error?.type === "error") {
      expect(error.data.detail).toBe("Не удалось получить ответ модели");
      expect(error.data.message?.content).toBe("Сбой");
    }
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/assistant\/threads\/t1\/messages\/stream$/);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Accept).toBe("text/event-stream");
  });

  it("не начинает стрим при ошибке HTTP и пробрасывает ApiError с деталью", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Чат в архиве — начните новый" }), { status: 409 })),
    );
    await expect(streamAssistantMessage("t1", { content: "Привет" }, () => undefined)).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      detail: "Чат в архиве — начните новый",
    });
    expect(new ApiError(409, "x", null)).toBeInstanceOf(ApiError);
  });
});
