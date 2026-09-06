import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, describeDetail } from "./client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("возвращает JSON и передаёт bearer-токен", async () => {
    const fetchMock = vi.fn(
      async (_input: string, _init?: RequestInit) =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiFetch<{ ok: boolean }>("/health", { token: "abc" });

    expect(result).toEqual({ ok: true });
    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });

  it("превращает ошибку API в ApiError с деталью и request-id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "Не найдено" }), {
            status: 404,
            headers: { "x-request-id": "rid-1" },
          }),
      ),
    );

    await expect(apiFetch("/missing", { token: null })).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      detail: "Не найдено",
      requestId: "rid-1",
    } satisfies Partial<ApiError>);
  });

  it("не ставит Content-Type для FormData", async () => {
    const fetchMock = vi.fn(
      async (_input: string, _init?: RequestInit) => new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    form.append("a", "b");
    await apiFetch("/upload", { method: "POST", body: form, token: null });

    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });
});

describe("ApiError", () => {
  it("показывает фразу сервера, а не список ошибок валидации", async () => {
    const body = {
      detail: [{ type: "value_error", loc: ["body", "email"], msg: "value is not a valid email address" }],
      message: "Проверьте данные — E-mail: некорректный адрес электронной почты",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 422 })));

    await expect(apiFetch("/auth/login", { token: null })).rejects.toMatchObject({
      status: 422,
      message: body.message,
    });
    vi.unstubAllGlobals();
  });

  it("без фразы сервера собирает текст из списка ошибок", () => {
    const detail = [{ loc: ["body", "email"], msg: "value is not a valid email address" }];
    expect(describeDetail(detail)).toBe("Проверьте данные — email: value is not a valid email address");
    expect(new ApiError(422, detail, null).message).toContain("email");
    expect(new ApiError(500, { unexpected: true }, null).message).toBe("Ошибка запроса (500)");
  });
});
