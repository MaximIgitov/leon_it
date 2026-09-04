import { API_BASE_URL, apiFetch, ApiError } from "./client";

export type SnapshotQuestion = {
  id: string;
  index: number;
  kind: "video" | "code";
  text: string;
  prep_seconds: number;
  max_answer_seconds: number;
  retakes_allowed: number;
  allows_followup: boolean;
};

export type AnswerStatus = "recording" | "uploaded" | "processing" | "done" | "failed" | "abandoned";

export type CodeRunResult = {
  status: "ok" | "error" | "timeout";
  stdout: string;
  stderr: string;
  exit_code: number | null;
  duration_ms: number;
  ran_at: string | null;
};

/** Секция кода в ответе: черновик до `submitted_at`, после — отправленное решение. */
export type CodeSubmission = {
  language: string;
  source: string;
  submitted_at: string | null;
  run_result: CodeRunResult | null;
};

export type CodeRunnerInfo = {
  enabled: boolean;
  languages: string[];
  max_source_bytes: number;
};

export type AvatarInfo = {
  enabled: boolean;
  clip_url: string | null;
  duration_s: number | null;
};

export type RoomAnswer = {
  id: string;
  question_index: number;
  attempt: number;
  is_final: boolean;
  status: AnswerStatus;
  upload_offset: number;
  media_size: number;
  duration_ms: number | null;
  recording_started_at: string;
  recording_ended_at: string | null;
  code_submission?: CodeSubmission | null;
};

export type InterviewState = {
  status: string;
  current_question_index: number;
  total_questions: number;
  questions: SnapshotQuestion[];
  answers: RoomAnswer[];
  settings: Record<string, unknown> & {
    prep_seconds?: number;
    max_answer_seconds?: number;
    retakes_allowed?: number;
    practice_question_enabled?: boolean;
    tts_enabled?: boolean;
  };
  revealed_at: Record<string, string>;
  expires_at: string;
  code_runner: CodeRunnerInfo;
};

export type RevealResult = {
  question: SnapshotQuestion;
  revealed_at: string;
  audio_url: string | null;
  audio_content_type: string | null;
  avatar: AvatarInfo;
};

export type CodeDraftBody = { language: string; source: string; submit?: boolean };
export type CodeRunBody = { language: string; source: string; stdin?: string };

export type ClientEvent = {
  kind: string;
  at_client_ms?: number;
  question_index?: number;
  answer_id?: string;
  payload?: Record<string, unknown>;
};

const base = (token: string) => `/public/invitations/${encodeURIComponent(token)}`;

/** Готов ли финальный блок уточняющих вопросов (нужны транскрипты ответов). */
export type FollowupStatus = {
  enabled: boolean;
  ready: boolean;
  pending: number;
  wait_seconds: number;
};

export const roomApi = {
  start: (token: string, clientInfo: Record<string, unknown>) =>
    apiFetch<InterviewState>(`${base(token)}/start`, {
      method: "POST",
      body: { client_info: clientInfo },
      token: null,
    }),
  state: (token: string) => apiFetch<InterviewState>(`${base(token)}/state`, { token: null }),
  reveal: (token: string, index: number) =>
    apiFetch<RevealResult>(`${base(token)}/questions/${index}/reveal`, { method: "POST", token: null }),
  createAnswer: (token: string, index: number, mimeType: string) =>
    apiFetch<{ answer: RoomAnswer; upload_chunk_max_bytes: number }>(
      `${base(token)}/questions/${index}/answers`,
      { method: "POST", body: { mime_type: mimeType }, token: null },
    ),
  completeAnswer: (
    token: string,
    answerId: string,
    body: { size: number; client_duration_ms?: number; mime_type?: string },
  ) =>
    apiFetch<RoomAnswer>(`${base(token)}/answers/${answerId}/complete`, {
      method: "POST",
      body,
      token: null,
    }),
  next: (token: string) => apiFetch<InterviewState>(`${base(token)}/next`, { method: "POST", token: null }),
  followups: (token: string) =>
    apiFetch<FollowupStatus>(`${base(token)}/followups`, { token: null }),
  saveCode: (token: string, questionId: string, body: CodeDraftBody) =>
    apiFetch<RoomAnswer>(`${base(token)}/answers/${encodeURIComponent(questionId)}/code`, {
      method: "PUT",
      body,
      token: null,
    }),
  runCode: (token: string, questionId: string, body: CodeRunBody) =>
    apiFetch<RoomAnswer>(`${base(token)}/answers/${encodeURIComponent(questionId)}/code/run`, {
      method: "POST",
      body,
      token: null,
    }),
  events: (token: string, events: ClientEvent[]) =>
    apiFetch<{ accepted: number; ignored: number }>(`${base(token)}/events`, {
      method: "POST",
      body: { events },
      token: null,
    }),
};

/**
 * Загрузить один кусок по смещению. При 409 сервер сообщает фактический размер
 * в заголовке Upload-Offset — с него и продолжаем.
 */
export async function uploadChunk(
  token: string,
  answerId: string,
  offset: number,
  chunk: Blob,
): Promise<{ ok: true; offset: number } | { ok: false; actualOffset: number }> {
  const response = await fetch(`${API_BASE_URL}${base(token)}/answers/${answerId}/chunks`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/offset+octet-stream",
      "Upload-Offset": String(offset),
    },
    body: chunk,
  });
  if (response.status === 409) {
    const actual = Number(response.headers.get("Upload-Offset") ?? "0");
    return { ok: false, actualOffset: Number.isFinite(actual) ? actual : 0 };
  }
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = (await response.json())?.detail ?? detail;
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(response.status, detail, response.headers.get("x-request-id"));
  }
  const body = (await response.json()) as RoomAnswer;
  return { ok: true, offset: body.upload_offset };
}
