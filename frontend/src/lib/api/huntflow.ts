import { apiFetch } from "./client";

export type HuntflowMode = "real" | "fake";
export type HuntflowConnectionStatus = "active" | "needs_account" | "error";
export type HuntflowPushStatus = "not_pushed" | "linked" | "queued" | "pushing" | "pushed" | "error";

export type HuntflowAccount = { id: number; name: string; nick: string | null };

export type HuntflowConnection = {
  connected: boolean;
  mode: HuntflowMode | null;
  status: HuntflowConnectionStatus | null;
  account: HuntflowAccount | null;
  owner_name: string | null;
  owner_email: string | null;
  last_error: string | null;
  last_checked_at: string | null;
  connected_at: string | null;
  connected_by_email: string | null;
  available_accounts: HuntflowAccount[];
  linked_vacancies: number;
  demo_available: boolean;
  can_manage: boolean;
};

export type HuntflowFunnelStatus = { id: number; name: string; type: string | null; order: number };

export type HuntflowVacancyLink = {
  vacancy_id: string;
  vacancy_title: string;
  vacancy_status: string;
  huntflow_vacancy_id: number;
  huntflow_vacancy_title: string;
  status_id: number | null;
  status_name: string | null;
  last_imported_at: string | null;
  created_at: string;
};

export type HuntflowVacancy = {
  id: number;
  position: string;
  state: string | null;
  company: string | null;
  links: HuntflowVacancyLink[];
};

export type HuntflowVacancies = { items: HuntflowVacancy[]; statuses: HuntflowFunnelStatus[] };

export type HuntflowImportResult = { total: number; created: number; existing: number; skipped: number };

export type HuntflowPushJob = {
  id: string;
  status: string;
  attempts: number;
  max_attempts: number;
  run_after: string | null;
  last_error: string | null;
};

export type HuntflowPush = {
  candidate_id: string;
  status: HuntflowPushStatus;
  interview_id: string | null;
  huntflow_applicant_id: number | null;
  huntflow_vacancy_id: number | null;
  huntflow_status_id: number | null;
  last_pushed_at: string | null;
  last_error: string | null;
  report_share_url: string | null;
  job: HuntflowPushJob | null;
};

export const CONNECTION_STATUS_LABELS: Record<HuntflowConnectionStatus, string> = {
  active: "Подключено",
  needs_account: "Выберите аккаунт",
  error: "Ошибка",
};

export const VACANCY_STATE_LABELS: Record<string, string> = {
  OPEN: "Открыта",
  HOLD: "На паузе",
  CLOSED: "Закрыта",
};

export const TOKEN_HINT =
  "Персональный токен выпускается в Huntflow: Настройки организации → API → Персональные токены. " +
  "Токен хранится в зашифрованном виде и используется только для передачи кандидатов и импорта соискателей.";

/** Активна ли передача прямо сейчас — страница опрашивает статус, пока это так. */
export function isPushInFlight(status: HuntflowPushStatus): boolean {
  return status === "queued" || status === "pushing";
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

/** Короткая подпись к кнопке «В Huntflow». */
export function describePush(push: HuntflowPush | null): string {
  if (!push || push.status === "not_pushed") return "не передан";
  if (push.status === "linked") return "соискатель найден, не передан";
  if (push.status === "queued") return "в очереди";
  if (push.status === "pushing") return "передаётся…";
  if (push.status === "pushed") {
    return push.last_pushed_at ? `передан ${formatDateTime(push.last_pushed_at)}` : "передан";
  }
  const retrying = push.job?.status === "queued";
  const reason = push.last_error ? `: ${push.last_error}` : "";
  return retrying ? `ошибка, будет повтор${reason}` : `ошибка${reason}`;
}

export const huntflowApi = {
  status: () => apiFetch<HuntflowConnection>("/integrations/huntflow"),
  connect: (body: { token?: string; demo?: boolean; account_id?: number }) =>
    apiFetch<HuntflowConnection>("/integrations/huntflow/connect", { method: "POST", body }),
  selectAccount: (accountId: number) =>
    apiFetch<HuntflowConnection>("/integrations/huntflow/account", {
      method: "POST",
      body: { account_id: accountId },
    }),
  disconnect: () => apiFetch<void>("/integrations/huntflow", { method: "DELETE" }),
  vacancies: () => apiFetch<HuntflowVacancies>("/integrations/huntflow/vacancies"),
  links: () => apiFetch<HuntflowVacancyLink[]>("/integrations/huntflow/links"),
  link: (vacancyId: string, body: { huntflow_vacancy_id: number; status_id?: number | null }) =>
    apiFetch<HuntflowVacancyLink>(`/integrations/huntflow/links/${vacancyId}`, { method: "PUT", body }),
  unlink: (vacancyId: string) =>
    apiFetch<void>(`/integrations/huntflow/links/${vacancyId}`, { method: "DELETE" }),
  importApplicants: (vacancyId: string) =>
    apiFetch<HuntflowImportResult>(`/integrations/huntflow/links/${vacancyId}/import`, { method: "POST" }),
  push: (candidateId: string, body: { interview_id?: string } = {}) =>
    apiFetch<HuntflowPush>(`/integrations/huntflow/candidates/${candidateId}/push`, { method: "POST", body }),
  pushStatus: (candidateId: string) =>
    apiFetch<HuntflowPush>(`/integrations/huntflow/candidates/${candidateId}/push`),
};
