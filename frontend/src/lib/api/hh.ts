import { apiFetch } from "./client";

export type HhMode = "fake" | "real";
export type HhConnectionStatus = "connected" | "error" | "disconnected";
export type HhDialogState =
  | "new"
  | "greeting_sent"
  | "awaiting_slot"
  | "link_sent"
  | "done"
  | "declined"
  | "needs_recruiter";

export type HhConnection = {
  id: string;
  mode: HhMode;
  status: HhConnectionStatus;
  employer_id: string;
  employer_name: string;
  last_error: string;
  connected_at: string;
  last_synced_at: string | null;
  webhook_url: string | null;
  /** false — токен подключён без refresh_token и сам не обновится. */
  token_refreshable?: boolean;
  expires_at?: string | null;
};

export type HhStatus = {
  mode: HhMode;
  configured: boolean;
  sync_interval_minutes: number;
  connection: HhConnection | null;
};

export type HhVacancyLink = {
  id: string;
  hh_vacancy_id: string;
  hh_title: string;
  hh_url: string;
  vacancy_id: string;
  vacancy_title: string;
  vacancy_status: string;
  dialog_enabled: boolean;
  max_days: number;
  negotiation_count: number;
  created_at: string;
};

export type HhVacancy = {
  id: string;
  name: string;
  url: string;
  area: string;
  salary: string;
  published_at: string | null;
  key_skills: string[];
  link: HhVacancyLink | null;
};

export type HhDialogSettings = {
  enabled: boolean;
  max_days: number;
  greeting: string;
  clarify: string;
  link: string;
};

export type HhDialog = HhDialogSettings & {
  placeholders: string[];
  preview: Record<"greeting" | "clarify" | "link", string>;
};

export type HhDialogMessage = {
  role: "bot" | "candidate" | "recruiter";
  text: string;
  at: string | null;
  hh_message_id: string | null;
  step: string | null;
};

export type HhNegotiation = {
  id: string;
  negotiation_id: string;
  state: HhDialogState;
  chosen_date: string | null;
  candidate_id: string;
  candidate_name: string;
  candidate_email: string;
  vacancy_id: string;
  vacancy_title: string;
  vacancy_link_id: string;
  hh_vacancy_id: string;
  interview_id: string | null;
  interview_status: string | null;
  messages: HhDialogMessage[];
  last_error: string;
  last_synced_at: string | null;
  created_at: string;
};

export const HH_DIALOG_STATE_LABELS: Record<HhDialogState, string> = {
  new: "Новый отклик",
  greeting_sent: "Ждём ответ",
  awaiting_slot: "Уточняем день",
  link_sent: "Ссылка отправлена",
  done: "Интервью пройдено",
  declined: "Отказался",
  needs_recruiter: "Нужен рекрутер",
};

export const HH_PLACEHOLDER_HINTS: Record<string, string> = {
  candidate_name: "имя кандидата",
  vacancy_title: "название вакансии",
  link: "ссылка на интервью",
  days: "окно в днях",
  date: "срок действия ссылки",
};

export const hhApi = {
  status: () => apiFetch<HhStatus>("/integrations/hh/status"),
  oauthStart: () => apiFetch<{ url: string }>("/integrations/hh/oauth/start", { method: "POST" }),
  connectDemo: () => apiFetch<HhStatus>("/integrations/hh/connect-demo", { method: "POST" }),
  connectToken: (body: { access_token: string; refresh_token?: string | null; expires_at?: string | null }) =>
    apiFetch<HhStatus>("/integrations/hh/connect-token", { method: "POST", body }),
  disconnect: () => apiFetch<HhStatus>("/integrations/hh/disconnect", { method: "POST" }),
  vacancies: () => apiFetch<HhVacancy[]>("/integrations/hh/vacancies"),
  importVacancy: (hhVacancyId: string) =>
    apiFetch<HhVacancyLink>(`/integrations/hh/vacancies/${encodeURIComponent(hhVacancyId)}/import`, {
      method: "POST",
    }),
  linkVacancy: (hhVacancyId: string, vacancyId: string) =>
    apiFetch<HhVacancyLink>(`/integrations/hh/vacancies/${encodeURIComponent(hhVacancyId)}/link`, {
      method: "POST",
      body: { vacancy_id: vacancyId },
    }),
  links: () => apiFetch<HhVacancyLink[]>("/integrations/hh/links"),
  dialog: (linkId: string) => apiFetch<HhDialog>(`/integrations/hh/links/${linkId}/dialog`),
  updateDialog: (linkId: string, body: HhDialogSettings) =>
    apiFetch<HhDialog>(`/integrations/hh/links/${linkId}/dialog`, { method: "PUT", body }),
  negotiations: (params: { candidate_id?: string; link_id?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.candidate_id) query.set("candidate_id", params.candidate_id);
    if (params.link_id) query.set("link_id", params.link_id);
    const suffix = query.toString();
    return apiFetch<HhNegotiation[]>(`/integrations/hh/negotiations${suffix ? `?${suffix}` : ""}`);
  },
  takeOver: (negotiationId: string, days?: number) =>
    apiFetch<HhNegotiation>(`/integrations/hh/negotiations/${negotiationId}/take-over`, {
      method: "POST",
      body: days ? { days } : {},
    }),
  sync: () =>
    apiFetch<{ job_id: string; queued: boolean }>("/integrations/hh/sync", { method: "POST" }),
};
