import type { Role } from "@/lib/api/accounts";

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Владелец",
  recruiter: "Рекрутер",
  hiring_manager: "Нанимающий менеджер",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  owner: "Управляет наймом, командой, интеграциями и настройками.",
  recruiter: "Создаёт вакансии, приглашает кандидатов и работает с отчётами.",
  hiring_manager: "Смотрит отчёты доступных вакансий, оставляет заметки и принимает решения.",
};

export function roleLabel(role: Role): string {
  return ROLE_LABELS[role] ?? role;
}
