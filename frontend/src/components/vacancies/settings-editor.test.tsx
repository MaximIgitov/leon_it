import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SettingsEditor, avatarHint } from "@/components/vacancies/settings-editor";
import type { Vacancy } from "@/lib/api/vacancies";

function vacancy(overrides: Partial<Vacancy>): Vacancy {
  return {
    id: "v1",
    title: "Python-разработчик",
    description: "",
    requirements: "",
    skills: [],
    level: null,
    language: "ru",
    status: "draft",
    rubric: [],
    settings: {
      intro_text: "",
      prep_seconds: 30,
      max_answer_seconds: 180,
      retakes_allowed: 1,
      practice_question_enabled: true,
      followups_enabled: false,
      followups_max: 1,
      tts_enabled: true,
      voice: "nova",
      avatar_enabled: false,
      invitation_days: 7,
      candidate_feedback_mode: "after_decision",
      candidate_feedback_after_days: 3,
    },
    question_count: 0,
    questions: [],
    created_at: "2026-09-05T10:00:00Z",
    updated_at: "2026-09-05T10:00:00Z",
    published_at: null,
    archived_at: null,
    ...overrides,
  };
}

const noop = () => undefined;

describe("настройки интервью: ИИ-аватар", () => {
  it("подсказка объясняет цену и что клипы готовятся при публикации", () => {
    expect(avatarHint(true)).toContain("при публикации");
    expect(avatarHint(true)).toContain("за минуту");
    expect(avatarHint(false)).toContain("не настроен");
  });

  it("переключатель активен только когда на сервере настроен провайдер", () => {
    const available = renderToStaticMarkup(
      <SettingsEditor vacancy={vacancy({ avatar_available: true })} editable onSaved={noop} onError={noop} />,
    );
    expect(available).toContain("ИИ-аватар интервьюера");
    expect(available).toContain("Клипы готовятся один раз при публикации");
    const unavailable = renderToStaticMarkup(
      <SettingsEditor vacancy={vacancy({ avatar_available: false })} editable onSaved={noop} onError={noop} />,
    );
    expect(unavailable).toContain("провайдер аватара не настроен");
    // Без провайдера ровно один переключатель выключен; с провайдером все активны.
    const disabledSwitches = (html: string) => (html.match(/role="switch"[^>]*\sdisabled=""/g) ?? []).length;
    expect(disabledSwitches(available)).toBe(0);
    expect(disabledSwitches(unavailable)).toBe(1);
  });
});
