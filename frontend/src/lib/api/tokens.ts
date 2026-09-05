import { API_BASE_URL, apiFetch } from "./client";

export type ApiScope =
  | "vacancies:read"
  | "vacancies:write"
  | "candidates:read"
  | "candidates:write"
  | "interviews:read"
  | "reports:read"
  | "media:read"
  | "knowledge:read"
  | "knowledge:write";

export type ApiTokenStatus = "active" | "expired" | "revoked";

export type ApiToken = {
  id: string;
  name: string;
  /** Первые символы токена («leonit_AbCdE») — чтобы отличать токены в списке. */
  token_prefix: string;
  scopes: ApiScope[];
  created_by_user_id: string | null;
  created_by_email: string | null;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  status: ApiTokenStatus;
};

/** Ответ на создание — единственный раз, когда виден сам токен. */
export type ApiTokenCreated = ApiToken & { token: string };

export const API_SCOPES: { value: ApiScope; label: string; description: string }[] = [
  { value: "vacancies:read", label: "Вакансии — чтение", description: "Список и карточки вакансий с вопросами." },
  { value: "vacancies:write", label: "Вакансии — запись", description: "Создание черновиков вакансий." },
  { value: "candidates:read", label: "Кандидаты — чтение", description: "Список кандидатов организации." },
  {
    value: "candidates:write",
    label: "Кандидаты — запись",
    description: "Создание кандидатов и приглашение на интервью.",
  },
  { value: "interviews:read", label: "Интервью — чтение", description: "Статусы, таймстемпы и решения." },
  { value: "reports:read", label: "Отчёты — чтение", description: "Заключение, транскрипты, ранжирование." },
  { value: "media:read", label: "Медиа — ссылки", description: "Подписанные ссылки на видео ответов в отчёте." },
];

export const TOKEN_STATUS_LABELS: Record<ApiTokenStatus, string> = {
  active: "Действует",
  expired: "Истёк",
  revoked: "Отозван",
};

/**
 * Документацию отдаёт бэкенд, а не фронтенд: страница Scalar читает
 * /api/openapi.json того же домена, поэтому ссылка строится от адреса API.
 */
export const API_DOCS_URL = `${API_BASE_URL}/docs/api`;

export const tokensApi = {
  list: () => apiFetch<ApiToken[]>("/organization/api-tokens"),
  create: (body: { name: string; scopes: ApiScope[]; expires_in_days?: number | null }) =>
    apiFetch<ApiTokenCreated>("/organization/api-tokens", { method: "POST", body }),
  revoke: (id: string) =>
    apiFetch<ApiToken>(`/organization/api-tokens/${id}`, { method: "DELETE" }),
};
