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
    const quotes = tile(base, "Цитаты подтверждены");
    expect(quotes.value).toBe("67 %");
    expect(quotes.hint).toBe("1 заключение с неподтверждёнными цитатами");
  });

  it("склоняет число заключений с неподтверждёнными цитатами", () => {
    expect(tile({ ...base, unverified_quotes_evaluations: 3 }, "Цитаты подтверждены").hint).toBe(
      "3 заключения с неподтверждёнными цитатами",
    );
    expect(tile({ ...base, unverified_quotes_evaluations: 5 }, "Цитаты подтверждены").hint).toBe(
      "5 заключений с неподтверждёнными цитатами",
    );
  });

  it("объясняет пустое значение и полное подтверждение", () => {
    const none = tile(
      { ...base, quote_verification_rate: null, unverified_quotes_evaluations: 0 },
      "Цитаты подтверждены",
    );
    expect(none.value).toBe("—");
    expect(none.hint).toBe("заключений с цитатами пока нет");
    const all = tile(
      { ...base, quote_verification_rate: 1, unverified_quotes_evaluations: 0 },
      "Цитаты подтверждены",
    );
    expect(all.value).toBe("100 %");
    expect(all.hint).toBe("во всех заключениях цитаты найдены в транскрипте");
  });

  it("подсказка среднего балла зависит от числа заключений", () => {
    expect(tile(base, "Средний балл").hint).toBe("оценено 3 интервью · до результата 4 ч");
    expect(tile({ ...base, evaluated: 0, avg_fit_score: null }, "Средний балл").value).toBe("—");
    expect(tile({ ...base, evaluated: 0, avg_fit_score: null }, "Средний балл").hint).toBe(
      "заключений пока нет",
    );
  });
});
