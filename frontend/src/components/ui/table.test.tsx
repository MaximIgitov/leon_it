import { describe, expect, it } from "vitest";

import { rowLinkTarget } from "@/components/ui/table";

const link = { href: "/vacancies/v1/interviews/i1" } as unknown as HTMLAnchorElement;
const row = { querySelector: (selector: string) => (selector === "a.table-row-link" ? link : null) };
const emptyRow = { querySelector: () => null };
// closest(selector) возвращает элемент, если цель клика лежит внутри одного из перечисленных.
const target = (matches: boolean) => ({ closest: () => (matches ? ({} as Element) : null) });

describe("клик по строке таблицы", () => {
  it("ведёт по ссылке строки, если клик по обычной ячейке", () => {
    expect(rowLinkTarget(row, target(false))).toBe(link);
    expect(rowLinkTarget(row, null)).toBe(link);
  });

  it("не перехватывает клики по кнопкам и другим ссылкам внутри строки", () => {
    expect(rowLinkTarget(row, target(true))).toBeNull();
  });

  it("ничего не делает для строк без ссылки", () => {
    expect(rowLinkTarget(emptyRow, target(false))).toBeNull();
  });
});
