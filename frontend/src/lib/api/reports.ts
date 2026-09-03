import { apiFetch } from "./client";
import type { Interview } from "./candidates";

export type AnswerDetail = {
  id: string;
  question_index: number;
  attempt: number;
  is_final: boolean;
  status: "recording" | "uploaded" | "processing" | "done" | "failed" | "abandoned";
  upload_offset: number;
  media_size: number;
  duration_ms: number | null;
  recording_started_at: string;
  recording_ended_at: string | null;
  media_url: string | null;
  audio_url?: string | null;
  media_content_type: string | null;
  transcript_text: string | null;
  transcript_segments: { start_s: number; end_s: number; text: string }[] | null;
  processing_error: string | null;
  question_text: string | null;
  question_id: string | null;
  parent_answer_id: string | null;
};

export type InterviewEvent = {
  id: string;
  kind: string;
  source: string;
  question_index: number | null;
  answer_id: string | null;
  at_client_ms: number | null;
  at_server: string;
  payload: Record<string, unknown>;
};

export type Evidence = {
  answer_id: string;
  question_index: number;
  quote: string;
  start_s: number | null;
  end_s: number | null;
  /** Проставляет сервер: цитата найдена в транскрипте дословно. */
  verified?: boolean;
};

export type EvaluationOutput = {
  summary: string;
  competency_scores: {
    competency_id: string;
    name: string;
    score: number;
    rationale: string;
    evidence: Evidence[];
  }[];
  question_assessments: {
    question_index: number;
    answer_id: string | null;
    score: number;
    covered_points: string[];
    missed_points: string[];
    comment: string;
    evidence: Evidence[];
  }[];
  strengths: string[];
  growth_areas: string[];
  risks: string[];
  skills: { name: string; level: string; evidence: Evidence[] }[];
  follow_up_checks: string[];
  red_flags: string[];
  confidence: number;
  transcript_quality_note: string | null;
};

export type CandidateFeedback = {
  greeting: string;
  strengths: string[];
  suggestions: string[];
  closing: string;
};

export type Recommendation = "fit" | "no_fit" | "needs_check";

export type Evaluation = {
  status: "pending" | "done" | "failed";
  fit_score: number | null;
  recommendation: Recommendation | null;
  output: EvaluationOutput | null;
  candidate_feedback: CandidateFeedback | null;
  model: string | null;
  prompt_version: string | null;
  evaluated_at: string | null;
  quotes_found?: number | null;
  quotes_total?: number | null;
  error: string | null;
};

export type RankingRow = {
  interview_id: string;
  candidate_id: string;
  candidate_name: string;
  candidate_email: string;
  status: string;
  fit_score: number | null;
  recommendation: Recommendation | null;
  evaluated_at: string | null;
  decision: string | null;
  completed_at: string | null;
};

export type Decision = "advance" | "reject" | "hold";

export type Note = {
  id: string;
  author_user_id: string | null;
  author_label: string;
  text: string;
  answer_id: string | null;
  at_s: number | null;
  created_at: string;
};

export type Share = {
  id: string;
  label: string;
  expires_at: string;
  revoked_at: string | null;
  include_integrity: boolean;
  allow_download: boolean;
  view_count: number;
  last_viewed_at: string | null;
  created_at: string;
  status: "active" | "expired" | "revoked";
  url: string | null;
};

export type PublicReport = {
  organization_name: string;
  vacancy_title: string;
  candidate_name: string;
  candidate_email: string | null;
  status: string;
  completed_at: string | null;
  decision: string | null;
  decision_note: string | null;
  evaluation: {
    status: string;
    fit_score: number | null;
    recommendation: Recommendation | null;
    output: EvaluationOutput | null;
    evaluated_at: string | null;
  } | null;
  answers: {
    id: string;
    question_index: number;
    question_text: string | null;
    attempt: number;
    duration_ms: number | null;
    media_url: string | null;
    media_content_type: string | null;
    transcript_text: string | null;
    transcript_segments: { start_s: number; end_s: number; text: string }[] | null;
    status: string;
  }[];
  notes: Note[];
  can_decide: boolean;
  can_note: boolean;
  integrity: Record<string, unknown> | null;
  expires_at: string;
};

export const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  fit: "Подходит",
  no_fit: "Не подходит",
  needs_check: "Нужна проверка",
};

export const DECISION_LABELS: Record<Decision, string> = {
  advance: "Дальше",
  reject: "Отказ",
  hold: "На паузе",
};

export const reportsApi = {
  answers: (interviewId: string) => apiFetch<AnswerDetail[]>(`/interviews/${interviewId}/answers`),
  events: (interviewId: string) => apiFetch<InterviewEvent[]>(`/interviews/${interviewId}/events`),
  evaluation: (interviewId: string) => apiFetch<Evaluation>(`/interviews/${interviewId}/evaluation`),
  reprocess: (interviewId: string) =>
    apiFetch<void>(`/interviews/${interviewId}/reprocess`, { method: "POST" }),
  ranking: (vacancyId: string) => apiFetch<RankingRow[]>(`/vacancies/${vacancyId}/ranking`),
  decide: (interviewId: string, body: { decision: Decision; note?: string }) =>
    apiFetch<Interview>(`/interviews/${interviewId}/decision`, { method: "POST", body }),
  notes: (interviewId: string) => apiFetch<Note[]>(`/interviews/${interviewId}/notes`),
  addNote: (interviewId: string, body: { text: string; answer_id?: string; at_s?: number }) =>
    apiFetch<Note>(`/interviews/${interviewId}/notes`, { method: "POST", body }),
  deleteNote: (interviewId: string, noteId: string) =>
    apiFetch<void>(`/interviews/${interviewId}/notes/${noteId}`, { method: "DELETE" }),
  shares: (interviewId: string) => apiFetch<Share[]>(`/interviews/${interviewId}/shares`),
  createShare: (
    interviewId: string,
    body: { label?: string; expires_in_days?: number; include_integrity?: boolean; allow_download?: boolean },
  ) => apiFetch<Share>(`/interviews/${interviewId}/shares`, { method: "POST", body }),
  revokeShare: (interviewId: string, shareId: string) =>
    apiFetch<Share>(`/interviews/${interviewId}/shares/${shareId}`, { method: "DELETE" }),
  extendShare: (interviewId: string, shareId: string, days = 14) =>
    apiFetch<Share>(`/interviews/${interviewId}/shares/${shareId}/extend?days=${days}`, { method: "POST" }),
};

export const publicReportsApi = {
  get: (token: string) => apiFetch<PublicReport>(`/public/reports/${encodeURIComponent(token)}`, { token: null }),
  decide: (token: string, body: { decision: Decision; note?: string }) =>
    apiFetch<void>(`/public/reports/${encodeURIComponent(token)}/decision`, { method: "POST", body, token: null }),
  addNote: (token: string, body: { text: string; answer_id?: string; at_s?: number }) =>
    apiFetch<Note>(`/public/reports/${encodeURIComponent(token)}/notes`, { method: "POST", body, token: null }),
};
