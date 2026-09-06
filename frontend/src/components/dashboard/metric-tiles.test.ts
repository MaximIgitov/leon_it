import { describe, expect, it } from "vitest";

import type { DashboardOverview } from "@/lib/api/dashboard";

import { TILE_COUNT, tiles } from "./metric-tiles";

const base: DashboardOverview = {
  period: { from: "2026-08-04T00:00:00Z", to: "2026-09-03T00:00:00Z", all_time: false },
  vacancy: null,
  invited: 7,
  completed: 4,
  evaluated: 3,
  decided: 3,
  awaiting_decision: 1,
  active_vacancies: 1,
  interviews_last_7d: 7,
  interviews_last_30d: 7,
  completion_rate: 0.5714,
  median_time_to_complete_h: 0.2,
  median_time_to_result_h: 4,
  avg_fit_score: 62.3,
  avg_retakes: 0.13,
  ai_agreement: 0.5,
  ai_agreement_pairs: 2,
  quote_verification_rate: 0.6667,
  unverified_quotes_evaluations: 1,
  flags_rate: 0,
  funnel: [],
  recommendation_breakdown: { fit: 2, no_fit: 1, needs_check: 0 },
  decision_breakdown: { advance: 1, reject: 1, hold: 1, pending: 1 },
};

function tile(data: DashboardOverview, label: string) {
  const found = tiles(data).find((item) => item.label === label);
  if (!found) throw new Error(`нет плитки «${label}»`);
  return found;
}

describe("плитки дашборда", () => {
  it("рисует все плитки, включая доверие к цитатам", () => {
    expect(tiles(base)).toHaveLength(TILE_COUNT);
    const quotes = tile(base, "Точность цитат");
    expect(quotes.value).toBe("67 %");
    expect(quotes.hint).toBe("Подтверждены ответами кандидатов");
  });

  it("считает воронку от приглашённых", () => {
    expect(tile(base, "Приглашено").value).toBe("7");
    expect(tile(base, "Завершили интервью").value).toBe("4");
    expect(tile(base, "Завершили интервью").hint).toBe("Из 7 приглашённых");
    expect(tile(base, "Конверсия").value).toBe("57 %");
  });

  it("объясняет пустые значения прочерком", () => {
    const empty = { ...base, quote_verification_rate: null, avg_fit_score: null, ai_agreement: null, evaluated: 0 };
    expect(tile(empty, "Точность цитат").value).toBe("—");
    expect(tile(empty, "Средний балл").value).toBe("—");
    expect(tile(empty, "Согласие с ИИ").value).toBe("—");
    expect(tile({ ...base, quote_verification_rate: 1 }, "Точность цитат").value).toBe("100 %");
  });

  it("склоняет число оценённых интервью и решений", () => {
    expect(tile(base, "Средний балл").hint).toBe("3 интервью оценены");
    expect(tile({ ...base, evaluated: 1 }, "Средний балл").hint).toBe("1 интервью оценено");
    expect(tile({ ...base, evaluated: 5 }, "Средний балл").hint).toBe("5 интервью оценены");
    expect(tile(base, "Согласие с ИИ").hint).toBe("На основе 2 решений");
    expect(tile({ ...base, ai_agreement_pairs: 1 }, "Согласие с ИИ").hint).toBe("На основе 1 решения");
  });
});
