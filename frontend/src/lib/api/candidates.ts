import { apiFetch } from "./client";

export type InterviewStatus =
  | "invited"
  | "opened"
  | "consented"
  | "in_progress"
  | "completed"
  | "processing"
  | "evaluated"
  | "reviewed"
  | "advanced"
  | "rejected"
  | "expired"
  | "cancelled";

export type Candidate = {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  source: "manual" | "bulk" | "hh" | "huntflow" | "api";
  notes: string;
  has_resume: boolean;
  newsletter_opt_in: boolean;
  external_ref: string | null;
  created_at: string;
  interview_count: number;
  last_interview_status: InterviewStatus | null;
};

export type Interview = {
  id: string;
  status: InterviewStatus;
  vacancy_id: string;
  vacancy_title: string;
  candidate_id: string;
  candidate_name: string;
  candidate_email: string;
  invited_at: string;
  expires_at: string;
  opened_at: string | null;
  consented_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  evaluated_at: string | null;
  decided_at: string | null;
  decision: string | null;
  current_question_index: number;
  question_count: number | null;
  link: string | null;
};

export type BulkCreateResult = {
  created: Candidate[];
  existing: Candidate[];
  skipped_lines: number;
  invited: number;
};

export type ConsentDocument = {
  slug: string;
  title: string;
  version: string;
  hash: string;
  required: boolean;
  checkbox_label: string | null;
};

export type InvitationPublic = {
  status: InterviewStatus;
  organization_name: string;
  vacancy_title: string;
  intro_text: string;
  question_count: number;
  estimated_minutes: number;
  prep_seconds: number;
  max_answer_seconds: number;
  retakes_allowed: number;
  practice_question_enabled: boolean;
  expires_at: string;
  needs_consent: boolean;
  candidate_full_name: string;
  candidate_email: string;
  consent_documents: ConsentDocument[];
  current_question_index: number;
};

export type LegalDocument = {
  slug: string;
  title: string;
  version: string;
  effective_date: string;
  operator: string;
  required: boolean;
  checkbox_label: string | null;
  hash: string;
  markdown: string;
};

export type EmailMessage = {
  id: string;
  kind: string;
  to_email: string;
  subject: string;
  body_text: string;
  status: "queued" | "sent" | "failed";
  provider: string | null;
  error: string | null;
  sent_at: string | null;
  created_at: string;
  interview_id: string | null;
};

export const INTERVIEW_STATUS_LABELS: Record<InterviewStatus, string> = {
  invited: "Приглашён",
  opened: "Открыл ссылку",
  consented: "Дал согласие",
  in_progress: "Проходит",
  completed: "Завершил",
  processing: "Обработка",
  evaluated: "Оценён",
  reviewed: "Просмотрен",
  advanced: "Дальше",
  rejected: "Отказ",
  expired: "Срок истёк",
  cancelled: "Отменено",
};

export const candidatesApi = {
  list: (search?: string) =>
    apiFetch<Candidate[]>(`/candidates${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  create: (body: { full_name: string; email: string; phone?: string; notes?: string }) =>
    apiFetch<Candidate>("/candidates", { method: "POST", body }),
  bulkCreate: (body: { text: string; vacancy_id?: string }) =>
    apiFetch<BulkCreateResult>("/candidates/bulk", { method: "POST", body }),
  get: (id: string) => apiFetch<Candidate>(`/candidates/${id}`),
  update: (id: string, body: { full_name?: string; phone?: string | null; notes?: string }) =>
    apiFetch<Candidate>(`/candidates/${id}`, { method: "PATCH", body }),
  interviews: (id: string) => apiFetch<Interview[]>(`/candidates/${id}/interviews`),
};

export const interviewsApi = {
  list: (vacancyId?: string) =>
    apiFetch<Interview[]>(`/interviews${vacancyId ? `?vacancy_id=${vacancyId}` : ""}`),
  invite: (body: {
    vacancy_id: string;
    candidate_id?: string;
    full_name?: string;
    email?: string;
    send_email?: boolean;
  }) => apiFetch<Interview>("/interviews", { method: "POST", body }),
  get: (id: string) => apiFetch<Interview>(`/interviews/${id}`),
  resend: (id: string) => apiFetch<Interview>(`/interviews/${id}/resend`, { method: "POST" }),
  cancel: (id: string) => apiFetch<Interview>(`/interviews/${id}/cancel`, { method: "POST" }),
};

export const publicApi = {
  invitation: (token: string) =>
    apiFetch<InvitationPublic>(`/public/invitations/${encodeURIComponent(token)}`, { token: null }),
  consent: (
    token: string,
    body: {
      full_name: string;
      email: string;
      personal_data_accepted: boolean;
      privacy_policy_accepted: boolean;
      newsletter_accepted: boolean;
      document_versions: Record<string, string>;
    },
  ) =>
    apiFetch<InvitationPublic>(`/public/invitations/${encodeURIComponent(token)}/consent`, {
      method: "POST",
      body,
      token: null,
    }),
};

export const legalApi = {
  get: (slug: string) => apiFetch<LegalDocument>(`/legal/${slug}`, { token: null }),
};

export const emailsApi = {
  list: () => apiFetch<EmailMessage[]>("/organization/emails"),
};
