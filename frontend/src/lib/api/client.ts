/*
 * Тонкий клиент к API.
 *
 * Все запросы к бэкенду идут через `apiFetch`: он подставляет базовый адрес,
 * bearer-токен сотрудника, разбирает ошибки в единый `ApiError` и пробрасывает
 * X-Request-ID, чтобы ошибку в интерфейсе можно было найти в логах сервера.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api";

const TOKEN_STORAGE_KEY = "leonit.access_token";

export class ApiError extends Error {
  readonly status: number;
  readonly requestId: string | null;
  readonly detail: unknown;
  /** Машиночитаемый код ошибки от бэкенда (например, `runner_disabled`). */
  readonly code: string | null;

  constructor(status: number, detail: unknown, requestId: string | null, code: string | null = null) {
    super(typeof detail === "string" ? detail : `Ошибка запроса (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
    this.detail = detail;
    this.code = code;
  }
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAccessToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* приватный режим: сессия не переживёт перезагрузку, но работать будет */
  }
}

export type ApiRequestOptions = Omit<RequestInit, "body" | "headers"> & {
  body?: unknown;
  headers?: Record<string, string>;
  /** Явный токен (например, токен кандидата) вместо сохранённого. */
  token?: string | null;
  /** Не разбирать JSON — вернуть Response как есть (файлы, потоки). */
  raw?: boolean;
};

export async function apiFetch<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { body, headers = {}, token, raw, ...init } = options;
  const finalHeaders: Record<string, string> = { Accept: "application/json", ...headers };
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isFormData) finalHeaders["Content-Type"] = "application/json";
  const bearer = token === undefined ? getAccessToken() : token;
  if (bearer) finalHeaders.Authorization = `Bearer ${bearer}`;

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: finalHeaders,
    body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
  });

  if (!response.ok) {
    let detail: unknown = response.statusText;
    let code: string | null = null;
    try {
      const payload = await response.json();
      detail = payload?.detail ?? payload;
      if (typeof payload?.code === "string") code = payload.code;
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(response.status, detail, response.headers.get("x-request-id"), code);
  }
  if (raw) return response as unknown as T;
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
