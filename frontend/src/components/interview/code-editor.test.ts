import { afterEach, describe, expect, it, vi } from "vitest";

import { INDENT, applyTab, clearDraft, draftStorageKey, readDraft, utf8Length, writeDraft } from "./code-editor";

describe("applyTab", () => {
  it("вставляет отступ в позицию курсора без выделения", () => {
    const result = applyTab("def f():\nreturn 1", 9, 9);
    expect(result.value).toBe(`def f():\n${INDENT}return 1`);
    expect(result.selectionStart).toBe(9 + INDENT.length);
    expect(result.selectionEnd).toBe(9 + INDENT.length);
  });

  it("заменяет однострочное выделение отступом", () => {
    const result = applyTab("abc", 1, 2);
    expect(result.value).toBe(`a${INDENT}c`);
    expect(result.selectionStart).toBe(1 + INDENT.length);
  });

  it("сдвигает все строки многострочного выделения", () => {
    const value = "a\nb\nc";
    const result = applyTab(value, 0, value.length);
    expect(result.value).toBe(`${INDENT}a\n${INDENT}b\n${INDENT}c`);
    expect(result.selectionStart).toBe(INDENT.length);
    expect(result.selectionEnd).toBe(result.value.length);
  });

  it("не трогает строку после завершающего переноса в выделении", () => {
    const result = applyTab("a\nb\nc", 0, 4);
    expect(result.value).toBe(`${INDENT}a\n${INDENT}b\nc`);
  });

  it("Shift+Tab убирает до двух пробелов в начале строк", () => {
    const value = `${INDENT}a\n   b\nc`;
    const result = applyTab(value, 0, value.length, true);
    expect(result.value).toBe("a\n b\nc");
    expect(result.selectionStart).toBe(0);
    expect(result.selectionEnd).toBe(result.value.length);
  });

  it("Shift+Tab без выделения убирает отступ текущей строки", () => {
    const value = `x\n${INDENT}y`;
    const result = applyTab(value, value.length, value.length, true);
    expect(result.value).toBe("x\ny");
    expect(result.selectionStart).toBe(3);
  });
});

describe("лимит размера", () => {
  it("считает байты UTF-8, а не символы", () => {
    expect(utf8Length("abc")).toBe(3);
    expect(utf8Length("привет")).toBe(12);
    expect(utf8Length("")).toBe(0);
  });

  it("код на границе лимита проходит, на байт больше — нет", () => {
    const limit = 16;
    const exact = "я".repeat(8); // 16 байт
    expect(utf8Length(exact) > limit).toBe(false);
    expect(utf8Length(exact + "a") > limit).toBe(true);
  });
});

describe("черновик в localStorage", () => {
  const store = new Map<string, string>();
  const localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
  };

  afterEach(() => {
    store.clear();
    vi.unstubAllGlobals();
  });

  it("сохраняет и читает черновик по токену и вопросу", () => {
    vi.stubGlobal("window", { localStorage });
    const key = draftStorageKey("token-abcdefghijklmnopqrstuvwxyz", "q1");
    expect(key).toBe("leonit.code.token-abcdefghij.q1");
    writeDraft(key, { language: "python", source: "print(1)" });
    expect(readDraft(key)).toMatchObject({ language: "python", source: "print(1)" });
    clearDraft(key);
    expect(readDraft(key)).toBeNull();
  });

  it("не падает без localStorage и на битых данных", () => {
    expect(readDraft("nope")).toBeNull();
    vi.stubGlobal("window", { localStorage });
    store.set("broken", "{not json");
    expect(readDraft("broken")).toBeNull();
    store.set("partial", JSON.stringify({ language: "python" }));
    expect(readDraft("partial")).toBeNull();
  });
});
