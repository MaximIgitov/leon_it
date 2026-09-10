import { randomUUID } from "node:crypto";

/*
 * Подготовка данных через API: регистрация рекрутера, вакансия, приглашение.
 * Сквозной тест проверяет интерфейс кандидата и отчёт, а не формы кабинета —
 * они покрыты отдельными сценариями.
 */
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000/api";

async function call<T>(path: string, init: RequestInit & { token?: string } = {}): Promise<T> {
  const { token, ...rest } = init;
  const response = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(rest.headers ?? {}),
    },
  });
  if (!response.ok) throw new Error(`${path} → ${response.status}: ${await response.text()}`);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type Seed = {
  token: string;
  email: string;
  password: string;
  vacancyId: string;
  interviewId: string;
  link: string;
};

export async function seedInterview(
  options: {
    prepSeconds?: number;
    maxAnswerSeconds?: number;
    interviewMode?: "live" | "push_to_talk";
    practice?: boolean;
  } = {},
): Promise<Seed> {
  const email = `recruiter-${randomUUID().slice(0, 8)}@example.com`;
  const password = "e2e-password-123";
  const { access_token: token } = await call<{ access_token: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: "Рекрутер E2E", organization_name: "Example IT" }),
  });
  const vacancy = await call<{ id: string }>("/vacancies", {
    method: "POST",
    token,
    body: JSON.stringify({
      title: "Python-разработчик",
      description: "Бэкенд на FastAPI и PostgreSQL",
      requirements: "Python 3.12, SQL, асинхронность",
      skills: ["Python", "PostgreSQL"],
    }),
  });
  await call(`/vacancies/${vacancy.id}`, {
    method: "PATCH",
    token,
    body: JSON.stringify({
      rubric: [{ id: "python", name: "Python", weight: 5, levels: { "1": "слабо", "4": "эксперт" } }],
      settings: {
        prep_seconds: options.prepSeconds ?? 2,
        max_answer_seconds: options.maxAnswerSeconds ?? 60,
        retakes_allowed: 1,
        practice_question_enabled: options.practice ?? true,
        tts_enabled: true,
        interview_mode: options.interviewMode ?? "push_to_talk",
      },
    }),
  });
  await call(`/vacancies/${vacancy.id}/questions`, {
    method: "PUT",
    token,
    body: JSON.stringify({
      questions: [
        { text: "Расскажите о своём опыте с Python", competency_ids: ["python"] },
        { text: "Что такое GIL и когда он мешает?", competency_ids: ["python"] },
      ],
    }),
  });
  await call(`/vacancies/${vacancy.id}/publish`, { method: "POST", token });
  const interview = await call<{ id: string; link: string }>("/interviews", {
    method: "POST",
    token,
    body: JSON.stringify({ vacancy_id: vacancy.id, full_name: "Иван Кандидат", email: "candidate@example.com" }),
  });
  return { token, email, password, vacancyId: vacancy.id, interviewId: interview.id, link: interview.link };
}

export async function getInterview(seed: Seed): Promise<{ status: string }> {
  return call(`/interviews/${seed.interviewId}`, { token: seed.token });
}

/**
 * Пройти интервью через API: согласия, старт, ответы (без записи видео —
 * загружаем небольшой WebM-заголовок), завершение. Нужен для сценариев
 * кабинета, где важен результат, а не путь кандидата в браузере.
 */
export async function completeInterview(seed: Seed): Promise<void> {
  const token = seed.link.split("/i/")[1];
  const page = await call<{ consent_documents: { slug: string; version: string }[] }>(
    `/public/invitations/${token}`,
  );
  await call(`/public/invitations/${token}/consent`, {
    method: "POST",
    body: JSON.stringify({
      full_name: "Иван Кандидат",
      email: "candidate@example.com",
      personal_data_accepted: true,
      privacy_policy_accepted: true,
      document_versions: Object.fromEntries(
        page.consent_documents.map((document) => [document.slug, document.version]),
      ),
    }),
  });
  const state = await call<{ total_questions: number }>(`/public/invitations/${token}/start`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  for (let index = 0; index < state.total_questions; index += 1) {
    await call(`/public/invitations/${token}/questions/${index}/reveal`, { method: "POST" });
    const created = await call<{ answer: { id: string } }>(
      `/public/invitations/${token}/questions/${index}/answers`,
      { method: "POST", body: JSON.stringify({ mime_type: "video/webm" }) },
    );
    const chunk = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 0, 0, 0, 0]);
    await fetch(`${API_URL}/public/invitations/${token}/answers/${created.answer.id}/chunks`, {
      method: "PATCH",
      headers: { "Content-Type": "application/offset+octet-stream", "Upload-Offset": "0" },
      body: chunk,
    });
    await call(`/public/invitations/${token}/answers/${created.answer.id}/complete`, {
      method: "POST",
      body: JSON.stringify({ size: chunk.byteLength, client_duration_ms: 4000 }),
    });
    await call(`/public/invitations/${token}/next`, { method: "POST" });
  }
}
