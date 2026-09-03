import type { Role } from "@/lib/api/accounts";

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Владелец",
  recruiter: "Рекрутер",
  hiring_manager: "Нанимающий менеджер",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  owner: "Всё, что рекрутер, плюс участники, приглашения, интеграции и настройки.",
  recruiter: "Вакансии, вопросы, кандидаты, приглашения, отчёты и дашборд.",
  hiring_manager: "Только отчёты по допущенным вакансиям, заметки и решение по кандидату.",
};

export function roleLabel(role: Role): string {
  return ROLE_LABELS[role] ?? role;
}
