import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ActionResult,
  ProposalPreview,
  actionHref,
  decisionLabel,
  proposalButton,
  proposalCaption,
  proposalHref,
  recommendationLabel,
} from "@/components/assistant/action-views";
import type { AssistantAction } from "@/lib/api/assistant";

function action(overrides: Partial<AssistantAction>): AssistantAction {
  return { kind: "done", tool: "list_vacancies", params: {}, summary: "", result: null, proposal: null, ...overrides };
}

describe("предложения ассистента", () => {
  it("рубрика показывается списком компетенций с весами и якорями", () => {
    const html = renderToStaticMarkup(
      <ProposalPreview
        proposal={{
          action: "update_rubric",
          summary: "Заменить рубрику",
          params: {
            vacancy_id: "v1",
            rubric: [
              {
                id: "python",
                name: "Python и асинхронность",
                description: "GIL, asyncio",
                weight: 5,
                levels: { "1": "Путается в базовых понятиях", "4": "Объясняет внутренности" },
              },
            ],
          },
        }}
      />,
    );
    expect(html).toContain("Python и асинхронность");
    expect(html).toContain("вес 5");
    expect(html).toContain("Якорные уровни");
    expect(html).toContain("Объясняет внутренности");
  });

  it("вопросы показываются с компетенциями и ожидаемыми пунктами, новые подсвечены", () => {
    const html = renderToStaticMarkup(
      <ProposalPreview
        proposal={{
          action: "replace_questions",
          summary: "Сохранить вопросы",
          params: {
            vacancy_id: "v1",
            questions: [
              { id: "q1", kind: "video", text: "Старый вопрос", expected_points: [], competency_ids: [], allows_followup: false, prep_seconds: null, max_answer_seconds: null, retakes_allowed: null },
              { kind: "video", text: "Как устроен GIL?", expected_points: ["блокировка байткода"], competency_ids: ["python"], allows_followup: false, prep_seconds: null, max_answer_seconds: null, retakes_allowed: null },
            ],
          },
        }}
        result={{ vacancy_id: "v1", questions: [{ text: "Как устроен GIL?", expected_points: ["блокировка байткода"], competency_ids: ["python"] }] }}
      />,
    );
    expect(html).toContain("Старый вопрос");
    expect(html).toContain("Как устроен GIL?");
    expect(html).toContain("блокировка байткода");
    expect(html).toContain("python");
    expect(html).toContain("border-primary/40");
  });

  it("вычитка показывает замечания и новую формулировку", () => {
    const html = renderToStaticMarkup(
      <ProposalPreview
        proposal={{ action: "replace_questions", summary: "Применить", params: { vacancy_id: "v1", questions: [] } }}
        result={{
          overall: "Два вопроса составные",
          items: [
            { question_id: "q1", text: "Расскажите про GIL и asyncio", issues: ["составной вопрос"], improved_text: "Расскажите, как устроен GIL" },
            { question_id: "q2", text: "Что такое индекс?", issues: [], improved_text: null },
          ],
        }}
      />,
    );
    expect(html).toContain("Два вопроса составные");
    expect(html).toContain("составной вопрос");
    expect(html).toContain("Новая формулировка");
    expect(html).toContain("Без замечаний");
  });

  it("приглашение и решение — понятными строками, а не JSON", () => {
    const invite = renderToStaticMarkup(
      <ProposalPreview
        proposal={{ action: "invite", summary: "", params: { vacancy_id: "v1", full_name: "Пётр Иванов", email: "p@example.com", send_email: true } }}
      />,
    );
    expect(invite).toContain("Пётр Иванов");
    expect(invite).toContain("p@example.com");
    expect(invite).toContain("уйдёт после подтверждения");
    const decide = renderToStaticMarkup(
      <ProposalPreview proposal={{ action: "decide", summary: "", params: { interview_id: "i1", decision: "reject", note: "слабая база" } }} />,
    );
    expect(decide).toContain("Отказ");
    expect(decide).toContain("слабая база");
    expect(decisionLabel("advance")).toBe("Дальше");
    expect(recommendationLabel("needs_check")).toBe("нужна проверка");
  });

  it("создание вакансии показывает содержимое: название, уровень, навыки, описание", () => {
    const html = renderToStaticMarkup(
      <ProposalPreview
        proposal={{
          action: "create_vacancy",
          summary: "Создать черновик",
          params: {
            title: "Go-разработчик",
            level: "senior",
            skills: ["Go", "gRPC"],
            description: "Платформа заказов",
            requirements: "Опыт от пяти лет",
          },
        }}
      />,
    );
    expect(html).toContain("Go-разработчик");
    expect(html).toContain("Senior");
    expect(html).toContain("gRPC");
    expect(html).toContain("Платформа заказов");
    expect(html).toContain("Опыт от пяти лет");
    expect(proposalCaption({ action: "create_vacancy", summary: "", params: {} })).toContain("черновик");
  });

  it("кнопка называет действие, необратимые — красные", () => {
    expect(proposalButton({ action: "create_vacancy", summary: "", params: {} })).toEqual({ label: "Создать черновик", destructive: false });
    expect(proposalButton({ action: "archive", summary: "", params: {} })).toEqual({ label: "Отправить в архив", destructive: true });
    expect(proposalButton({ action: "decide", summary: "", params: { decision: "reject" } })).toEqual({ label: "Сохранить отказ", destructive: true });
    expect(proposalButton({ action: "decide", summary: "", params: { decision: "advance" } }).label).toBe("Отправить дальше");
    expect(proposalButton({ action: "invite", summary: "", params: { send_email: false } }).label).toBe("Добавить приглашение");
    expect(proposalButton({ action: "unknown", summary: "", params: {} }).label).toBe("Подтвердить");
  });

  it("после подтверждения есть ссылка на то, что изменилось", () => {
    expect(proposalHref({ action: "replace_questions", summary: "", params: { vacancy_id: "v1" } })).toEqual({ href: "/vacancies/v1?tab=questions", label: "Открыть вопросы" });
    expect(proposalHref({ action: "update_rubric", summary: "", params: { vacancy_id: "v1" } })?.href).toBe("/vacancies/v1?tab=rubric");
    expect(proposalHref({ action: "publish", summary: "", params: { vacancy_id: "v1" } })?.href).toBe("/vacancies/v1");
    expect(proposalHref({ action: "decide", summary: "", params: { interview_id: "i1", vacancy_id: "v1", decision: "advance" } })?.href).toBe("/vacancies/v1/interviews/i1");
    expect(proposalHref({ action: "decide", summary: "", params: { interview_id: "i1" } })).toBeNull();
    expect(actionHref(action({ tool: "generate_rubric", params: { vacancy_id: "v1" } }))).toEqual({ href: "/vacancies/v1?tab=rubric", label: "Открыть рубрику" });
    expect(actionHref(action({ tool: "get_vacancy", params: {}, result: { id: "v2", title: "Python" } }))?.href).toBe("/vacancies/v2");
    expect(actionHref(action({ tool: "get_interview", params: { interview_id: "i1" }, result: { vacancy_id: "v1" } }))?.href).toBe("/vacancies/v1/interviews/i1");
    expect(actionHref(action({ tool: "get_candidate", params: { candidate_id: "c1" } }))?.href).toBe("/candidates/c1");
    expect(actionHref(action({ tool: "list_vacancies" }))).toBeNull();
    expect(actionHref(action({ kind: "error", tool: "get_vacancy", params: { vacancy_id: "v1" } }))).toBeNull();
  });

  it("подпись под кнопкой говорит, что именно произойдёт после подтверждения", () => {
    expect(proposalCaption({ action: "invite", summary: "", params: { send_email: true } })).toContain("письмо");
    expect(proposalCaption({ action: "invite", summary: "", params: { send_email: false } })).toContain("без письма");
    expect(proposalCaption({ action: "update_rubric", summary: "", params: {} })).toContain("рубрику");
    expect(proposalCaption({ action: "replace_questions", summary: "", params: {} })).toContain("вопросы");
    expect(proposalCaption({ action: "something_new", summary: "", params: {} })).toContain("после вашего подтверждения");
  });
});

describe("результаты инструментов", () => {
  it("поиск по базе знаний — списком фрагментов", () => {
    const html = renderToStaticMarkup(
      <ActionResult
        action={action({
          tool: "search_knowledge",
          result: [{ document_id: "d1", title: "Найм", position: 0, text: "Этапы отбора: отклик, интервью", score: 5.1 }],
        })}
      />,
    );
    expect(html).toContain("Найм");
    expect(html).toContain("фрагмент 1");
    expect(html).toContain("Этапы отбора");
    expect(html).not.toContain("Показать данные");
  });

  it("рейтинг и список вакансий — таблицами с русскими подписями", () => {
    const ranking = renderToStaticMarkup(
      <ActionResult
        action={action({
          tool: "ranking",
          result: { vacancy_id: "v1", rows: [{ rank: 1, interview_id: "i1", candidate_name: "Анна", fit_score: 59.5, recommendation: "needs_check", status: "evaluated", decision: null }] },
        })}
      />,
    );
    expect(ranking).toContain("Анна");
    expect(ranking).toContain("59.5");
    expect(ranking).toContain("нужна проверка");
    expect(ranking).toContain("оценён");
    const vacancies = renderToStaticMarkup(
      <ActionResult action={action({ tool: "list_vacancies", result: [{ id: "v1", title: "Python", status: "published", level: "middle", question_count: 3 }] })} />,
    );
    expect(vacancies).toContain("опубликована");
    expect(vacancies).toContain("Вопросов");
  });

  it("неизвестный инструмент и пустой результат не показывают сырых данных", () => {
    // Технических вставок в чате нет: что прочитал инструмент, пересказывает сам ассистент.
    expect(renderToStaticMarkup(<ActionResult action={action({ tool: "vacancy_summary", result: { invited_total: 3 } })} />)).toBe("");
    expect(renderToStaticMarkup(<ActionResult action={action({ result: null })} />)).toBe("");
  });
});
