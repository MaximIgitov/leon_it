import { describe, expect, it } from "vitest";

import { describeKind, formatSize, parseTags } from "./knowledge";

describe("knowledge helpers", () => {
  it("форматирует размер файла по-русски", () => {
    expect(formatSize(512)).toBe("512 Б");
    expect(formatSize(20 * 1024)).toBe("20 КБ");
    expect(formatSize(3.5 * 1024 * 1024)).toBe("3.5 МБ");
  });

  it("описывает вид документа по источнику", () => {
    expect(describeKind({ kind: "text", source_name: null })).toBe("текст");
    expect(describeKind({ kind: "file", source_name: "Ценности.DOCX" })).toBe("файл docx");
    expect(describeKind({ kind: "file", source_name: null })).toBe("файл");
  });

  it("разбирает теги как бэкенд: без дублей, в нижнем регистре", () => {
    expect(parseTags(" HR, hr ,Культура,, ")).toEqual(["hr", "культура"]);
    expect(parseTags("")).toEqual([]);
  });
});
