import { apiFetch } from "./client";

export type VacancyStatus = "draft" | "published" | "archived";
export type QuestionKind = "video" | "code";
export type FeedbackMode = "off" | "after_decision" | "auto_after_days";
export type VacancyLevel = "intern" | "junior" | "middle" | "senior" | "lead";

export type RubricCompetency = {
  id: string;
  name: string;
  description: string;
  weight: number;
  levels: Record<string, string>;
};

export type InterviewMode = "live" | "push_to_talk";

export const INTERVIEW_MODE_LABELS: Record<InterviewMode, string> = {
  live: "Живой диалог",
  push_to_talk: "Кнопка ответа",
};

export const INTERVIEW_MODE_HINTS: Record<InterviewMode, string> = {
  live: "Интервьюер задаёт вопрос голосом, кандидат отвечает как в разговоре: пауза завершает ответ, следующий вопрос звучит сам. Перезапись в этом формате недоступна.",
  push_to_talk: "Кандидат сам нажимает «Начать ответ» и «Завершить ответ»; есть время на подготовку и перезапись.",
};

export type InterviewSettings = {
  intro_text: string;
  prep_seconds: number;
  max_answer_seconds: number;
  retakes_allowed: number;
  practice_question_enabled: boolean;
  followups_enabled: boolean;
  followups_max: number;
  tts_enabled: boolean;
  voice: string;
  avatar_enabled: boolean;
  interview_mode: InterviewMode;
  invitation_days: number;
  candidate_feedback_mode: FeedbackMode;
  candidate_feedback_after_days: number;
};

export type Question = {
  id: string;
  position: number;
  kind: QuestionKind;
  text: string;
  expected_points: string[];
  competency_ids: string[];
  allows_followup: boolean;
  prep_seconds: number | null;
  max_answer_seconds: number | null;
  retakes_allowed: number | null;
};

export type QuestionDraft = Omit<Question, "id" | "position"> & { id?: string };

export type VacancyListItem = {
  id: string;
  title: string;
  status: VacancyStatus;
  level: VacancyLevel | null;
  skills: string[];
  question_count: number;
  created_at: string;
  updated_at: string;
  published_at: string | null;
};

export type Vacancy = {
  id: string;
  title: string;
  description: string;
  requirements: string;
  skills: string[];
  level: VacancyLevel | null;
  language: string;
  status: VacancyStatus;
  rubric: RubricCompetency[];
  settings: InterviewSettings;
  question_count: number;
  questions: Question[];
  /** Настроен ли на сервере провайдер ИИ-аватара; без него переключатель неактивен. */
  avatar_available?: boolean;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  archived_at: string | null;
};

export type VacancyQuickResult = { vacancy: Vacancy; notes: string; source_name: string | null };

export type VacancyUpdate = Partial<{
  title: string;
  description: string;
  requirements: string;
  skills: string[];
  level: VacancyLevel | null;
  rubric: RubricCompetency[];
  settings: InterviewSettings;
}>;

export const VACANCY_STATUS_LABELS: Record<VacancyStatus, string> = {
  draft: "Черновик",
  published: "Опубликована",
  archived: "В архиве",
};

export const LEVEL_LABELS: Record<VacancyLevel, string> = {
  intern: "Стажёр",
  junior: "Junior",
  middle: "Middle",
  senior: "Senior",
  lead: "Lead",
};

export const FEEDBACK_MODE_LABELS: Record<FeedbackMode, string> = {
  off: "Не отправлять",
  after_decision: "После решения рекрутера",
  auto_after_days: "Автоматически через N дней",
};

export const vacanciesApi = {
  list: (status?: VacancyStatus) =>
    apiFetch<VacancyListItem[]>(`/vacancies${status ? `?status=${status}` : ""}`),
  get: (id: string) => apiFetch<Vacancy>(`/vacancies/${id}`),
  create: (body: { title: string; description?: string; requirements?: string }) =>
    apiFetch<Vacancy>("/vacancies", { method: "POST", body }),
  quickFromText: (text: string) =>
    apiFetch<VacancyQuickResult>("/vacancies/quick", { method: "POST", body: { text } }),
  quickFromFile: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return apiFetch<VacancyQuickResult>("/vacancies/quick/upload", { method: "POST", body: form });
  },
  update: (id: string, body: VacancyUpdate) =>
    apiFetch<Vacancy>(`/vacancies/${id}`, { method: "PATCH", body }),
  replaceQuestions: (id: string, questions: QuestionDraft[]) =>
    apiFetch<Vacancy>(`/vacancies/${id}/questions`, { method: "PUT", body: { questions } }),
  publish: (id: string) => apiFetch<Vacancy>(`/vacancies/${id}/publish`, { method: "POST" }),
  unpublish: (id: string) => apiFetch<Vacancy>(`/vacancies/${id}/unpublish`, { method: "POST" }),
  archive: (id: string) => apiFetch<Vacancy>(`/vacancies/${id}/archive`, { method: "POST" }),
  restore: (id: string) => apiFetch<Vacancy>(`/vacancies/${id}/restore`, { method: "POST" }),
};
