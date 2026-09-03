import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "./client";

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
