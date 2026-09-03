/* Форматирование чисел дашборда: пустое значение везде показывается как «—». */

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("ru-RU");
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)} %`;
}

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(value >= 10 ? 0 : 1);
}

/** Часы → «< 1 ч», «6 ч», «2 дн 4 ч». */
export function formatHours(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1) return "< 1 ч";
  const hours = Math.round(value);
  if (hours < 48) return `${hours} ч`;
  const days = Math.floor(hours / 24);
  const rest = hours % 24;
  return rest ? `${days} дн ${rest} ч` : `${days} дн`;
}

export function formatDay(iso: string): string {
  // Дата без времени: разбираем как локальную, чтобы не уехать на день назад.
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

export function formatDayLong(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** Русское склонение: 1 решение, 2 решения, 5 решений. */
export function plural(count: number, forms: [string, string, string]): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
  return forms[2];
}
