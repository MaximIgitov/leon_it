import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { IntegrityBadge, IntegrityPanel } from "@/components/reports/integrity-panel";
import type { IntegrityObservation, IntegrityReport } from "@/lib/api/reports";

function observation(overrides: Partial<IntegrityObservation> = {}): IntegrityObservation {
  return {
    code: "away_during_answer",
    level: "attention",
    title: "Кандидат переключался с вкладки во время ответа",
    detail: "Вопрос 1: окно теряло фокус 2 раза, суммарно 30 с.",
    question_index: 0,
    evidence: { count: 2, total_ms: 30000 },
    review: null,
    ...overrides,
  };
}

function report(overrides: Partial<IntegrityReport> = {}): IntegrityReport {
  return {
    level: "attention",
    level_label: "обратить внимание",
    observations: [observation()],
    checked: true,
    flags: 1,
    ...overrides,
  };
}

describe("панель достоверности", () => {
  it("показывает наблюдения и кнопки решения ревьюеру", () => {
    const html = renderToStaticMarkup(<IntegrityPanel report={report()} onReview={() => {}} />);

    expect(html).toContain("Проверка записи");
    expect(html).toContain("Кандидат переключался с вкладки во время ответа");
    expect(html).toContain("Подтвердить");
    expect(html).toContain("Ложное срабатывание");
    // Оговорка про границы применения обязательна: это не приговор кандидату.
    expect(html).toContain("личность и мимика не анализируются");
  });

  it("без права решения показывает наблюдения только для чтения", () => {
    const html = renderToStaticMarkup(<IntegrityPanel report={report()} readOnly />);

    expect(html).toContain("Кандидат переключался с вкладки во время ответа");
    expect(html).not.toContain("Подтвердить");
  });

  it("сообщает, когда замечаний нет и когда данных ещё нет", () => {
    const clean = renderToStaticMarkup(
      <IntegrityPanel report={report({ level: "info", observations: [], flags: 0 })} />,
    );
    expect(clean).toContain("замечаний не найдено");
    expect(clean).toContain("Без замечаний");

    const empty = renderToStaticMarkup(
      <IntegrityPanel report={report({ checked: false, observations: [], flags: 0 })} />,
    );
    expect(empty).toContain("кандидат не начинал запись");
  });

  it("показывает вердикт ревьюера рядом с наблюдением", () => {
    const html = renderToStaticMarkup(
      <IntegrityPanel
        readOnly
        report={report({
          observations: [
            observation({
              review: {
                verdict: "false_positive",
                comment: "Это был тестовый прогон",
                reviewer: "Мария Кузнецова",
                reviewed_at: "2026-09-04T10:00:00Z",
              },
            }),
          ],
        })}
      />,
    );

    expect(html).toContain("Ложное срабатывание");
    expect(html).toContain("Мария Кузнецова");
    expect(html).toContain("Это был тестовый прогон");
  });

  it("бейдж скрыт, пока данных нет, и показывает уровень с числом флагов", () => {
    expect(renderToStaticMarkup(<IntegrityBadge report={null} />)).toBe("");
    expect(
      renderToStaticMarkup(<IntegrityBadge report={report({ checked: false })} />),
    ).toBe("");

    const badge = renderToStaticMarkup(
      <IntegrityBadge report={report({ level: "risk", flags: 2 })} />,
    );
    expect(badge).toContain("Высокий риск");
    expect(badge).toContain("2");
  });
});
