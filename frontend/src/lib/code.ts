/*
 * Общее для секции кода: подписи языков и форматирование размеров. Список
 * доступных языков задаёт бэкенд (CODE_LANGUAGES) — здесь только, как их показать.
 */

export const LANGUAGE_LABELS: Record<string, string> = {
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
  go: "Go",
  java: "Java",
  sql: "SQL",
  kotlin: "Kotlin",
  csharp: "C#",
  cpp: "C++",
  rust: "Rust",
  php: "PHP",
  ruby: "Ruby",
};

export function languageLabel(language: string): string {
  const known = LANGUAGE_LABELS[language.toLowerCase()];
  if (known) return known;
  return language.charAt(0).toUpperCase() + language.slice(1);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} КБ`;
}
