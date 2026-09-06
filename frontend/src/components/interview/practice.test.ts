import { describe, expect, it } from "vitest";

import { formatClock } from "@/components/interview/practice";

describe("тренировочный вопрос", () => {
  it("таймер записи показывается как минуты:секунды, а не голым числом", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(7)).toBe("0:07");
    expect(formatClock(30)).toBe("0:30");
    expect(formatClock(75)).toBe("1:15");
    expect(formatClock(-3)).toBe("0:00");
  });
});
