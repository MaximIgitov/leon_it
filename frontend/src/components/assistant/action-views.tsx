import { Badge } from "@/components/ui/badge";
import type { AssistantAction, Proposal } from "@/lib/api/assistant";
import type { QuestionDraft, RubricCompetency } from "@/lib/api/vacancies";

/*
 * Содержимое карточек ассистента. Предложение (рубрика, вопросы, приглашение,
 * решение) показываем в человеческом виде до подтверждения — иначе пользователь
 * подтверждал бы JSON. Результаты инструментов-списков — компактными таблицами;
 * всё остальное остаётся доступным через «Показать данные».
 */

const DECISION_LABELS: Record<string, string> = {
  advance: "Дальше",
  reject: "Отказ",
  hold: "На паузе",
};

const RECOMMENDATION_LABELS: Record<string, string> = {
  fit: "подходит",
  no_fit: "не подходит",
  needs_check: "нужна проверка",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "черновик",
  published: "опубликована",
  archived: "архив",
  invited: "приглашён",
  opened: "открыл ссылку",
  consented: "дал согласие",
  in_progress: "проходит",
  completed: "завершил",
  processing: "обрабатывается",
  evaluated: "оценён",
  reviewed: "на паузе",
  advanced: "дальше",
  rejected: "отказ",
  expired: "истекла",
  cancelled: "отменено",
};

export function decisionLabel(value: unknown): string {
  return typeof value === "string" ? (DECISION_LABELS[value] ?? value) : "—";
}

export function recommendationLabel(value: unknown): string {
  return typeof value === "string" ? (RECOMMENDATION_LABELS[value] ?? value) : "—";
}

export function statusLabel(value: unknown): string {
  return typeof value === "string" ? (STATUS_LABELS[value] ?? value) : "—";
}

const PROPOSAL_CAPTIONS: Record<string, string> = {
  invite: "Кандидату уйдёт письмо с приглашением",
  decide: "Решение сохранится в карточке кандидата",
  publish: "Вакансия откроется для приглашений",
  archive: "Вакансия уйдёт в архив",
  update_rubric: "Заменит текущую рубрику вакансии",
  replace_questions: "Заменит текущие вопросы вакансии",
};

/** Подпись под кнопкой «Подтвердить»: что именно произойдёт, а не абстрактное «необратимое». */
export function proposalCaption(proposal: Proposal): string {
  const effect =
    proposal.action === "invite" && proposal.params.send_email === false
      ? "Приглашение появится в списке без письма кандидату"
      : (PROPOSAL_CAPTIONS[proposal.action] ?? "Изменение применится");
  return `${effect} — только после вашего подтверждения`;
}

function clip(text: unknown, limit: number): string {
  const value = typeof text === "string" ? text : "";
  return value.length > limit ? `${value.slice(0, limit).trimEnd()}…` : value;
}

function asArray<T = Record<string, unknown>>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function Table({
  columns,
  rows,
  keyOf,
}: {
  columns: { key: string; label: string; render?: (row: Record<string, unknown>) => React.ReactNode }[];
  rows: Record<string, unknown>[];
  keyOf: (row: Record<string, unknown>, index: number) => string;
}) {
  if (rows.length === 0) return <p className="text-xs text-muted-foreground">Пусто.</p>;
  return (
    <div className="thin-scrollbar overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground">
            {columns.map((column) => (
              <th key={column.key} className="pb-1 pr-3 font-medium">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={keyOf(row, index)} className="border-t">
              {columns.map((column) => (
                <td key={column.key} className="py-1 pr-3 align-top">
                  {column.render ? column.render(row) : String(row[column.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RubricPreview({ rubric }: { rubric: RubricCompetency[] }) {
  return (
    <ol className="space-y-2">
      {rubric.map((item) => (
        <li key={item.id} className="rounded-md border bg-background/60 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{item.name}</span>
            <Badge variant="secondary" className="font-normal">
              вес {item.weight}
            </Badge>
          </div>
          {item.description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{item.description}</p>
          ) : null}
          {Object.keys(item.levels ?? {}).length ? (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                Якорные уровни
              </summary>
              <ul className="mt-1 space-y-0.5 text-xs">
                {["1", "2", "3", "4"].map((level) =>
                  item.levels?.[level] ? (
                    <li key={level} className="flex gap-2">
                      <span className="shrink-0 font-mono text-muted-foreground">{level}</span>
                      <span>{item.levels[level]}</span>
                    </li>
                  ) : null,
                )}
              </ul>
            </details>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function QuestionsPreview({
  questions,
  highlight,
}: {
  questions: QuestionDraft[];
  highlight?: Set<string>;
}) {
  return (
    <ol className="space-y-2">
      {questions.map((question, index) => {
        const isNew = highlight ? !question.id || highlight.has(question.id) : false;
        return (
          <li
            key={question.id ?? `new-${index}`}
            className={`rounded-md border bg-background/60 p-2 ${isNew ? "border-primary/40" : ""}`}
          >
            <div className="flex gap-2">
              <span className="shrink-0 font-mono text-xs text-muted-foreground">{index + 1}</span>
              <div className="min-w-0 flex-1">
                <p>{question.text}</p>
                {question.competency_ids?.length ? (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {question.competency_ids.map((id) => (
                      <Badge key={id} variant="outline" className="font-mono text-[10px] font-normal">
                        {id}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                {question.expected_points?.length ? (
                  <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
                    {question.expected_points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Что именно предлагается подтвердить — в человеческом виде. */
export function ProposalPreview({ proposal, result }: { proposal: Proposal; result?: unknown }) {
  const params = proposal.params as Record<string, unknown>;
  switch (proposal.action) {
    case "update_rubric":
      return <RubricPreview rubric={asArray<RubricCompetency>(params.rubric)} />;
    case "replace_questions": {
      const questions = asArray<QuestionDraft>(params.questions);
      // Вычитка возвращает те же вопросы с улучшенными формулировками — покажем замечания.
      const review = result && typeof result === "object" ? (result as Record<string, unknown>) : null;
      const items = review ? asArray<Record<string, unknown>>(review.items) : [];
      if (items.length) {
        return (
          <div className="space-y-2">
            {typeof review?.overall === "string" && review.overall ? (
              <p className="text-xs text-muted-foreground">{review.overall}</p>
            ) : null}
            <ol className="space-y-2">
              {items.map((item, index) => (
                <li key={String(item.question_id ?? index)} className="rounded-md border bg-background/60 p-2">
                  <p className="text-xs text-muted-foreground">{clip(item.text, 220)}</p>
                  {asArray<string>(item.issues).length ? (
                    <ul className="mt-1 list-disc pl-4 text-xs">
                      {asArray<string>(item.issues).map((issue) => (
                        <li key={issue}>{issue}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-1 text-xs text-success">Без замечаний</p>
                  )}
                  {typeof item.improved_text === "string" && item.improved_text ? (
                    <p className="mt-1 text-sm">
                      <span className="text-muted-foreground">Новая формулировка: </span>
                      {item.improved_text}
                    </p>
                  ) : null}
                </li>
              ))}
            </ol>
          </div>
        );
      }
      const generated = result && typeof result === "object" ? (result as Record<string, unknown>) : null;
      const fresh = new Set(asArray<QuestionDraft>(generated?.questions).map((q) => q.text));
      const highlight = new Set(questions.filter((q) => !q.id || fresh.has(q.text)).map((q) => q.id ?? q.text));
      return <QuestionsPreview questions={questions} highlight={highlight.size ? highlight : undefined} />;
    }
    case "invite":
      return (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Кандидат</dt>
          <dd>{String(params.full_name ?? "—")}</dd>
          <dt className="text-muted-foreground">E-mail</dt>
          <dd className="break-all">{String(params.email ?? "—")}</dd>
          <dt className="text-muted-foreground">Письмо</dt>
          <dd>{params.send_email === false ? "не отправлять" : "уйдёт после подтверждения"}</dd>
        </dl>
      );
    case "decide":
      return (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Решение</dt>
          <dd>
            <Badge variant={params.decision === "reject" ? "destructive" : "default"}>
              {decisionLabel(params.decision)}
            </Badge>
          </dd>
          {typeof params.note === "string" && params.note ? (
            <>
              <dt className="text-muted-foreground">Заметка</dt>
              <dd>{params.note}</dd>
            </>
          ) : null}
        </dl>
      );
    default:
      return null;
  }
}

/** Результат выполненного инструмента: таблица или список для известных, JSON — для остальных. */
export function ActionResult({ action }: { action: AssistantAction }) {
  if (action.kind !== "done" || action.result === null || action.result === undefined) return null;
  const result = action.result;
  const json = JSON.stringify(result, null, 2);
  let view: React.ReactNode = null;
  switch (action.tool) {
    case "search_knowledge": {
      const hits = asArray(result);
      view = hits.length ? (
        <ul className="space-y-1.5">
          {hits.map((hit, index) => (
            <li key={`${String(hit.document_id)}-${index}`} className="rounded-md border bg-background/60 p-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{String(hit.title ?? "")}</span>
                <span className="text-muted-foreground">фрагмент {Number(hit.position ?? 0) + 1}</span>
              </div>
              <p className="mt-0.5 whitespace-pre-line text-muted-foreground">{clip(hit.text, 260)}</p>
            </li>
          ))}
        </ul>
      ) : null;
      break;
    }
    case "list_vacancies":
      view = (
        <Table
          rows={asArray(result)}
          keyOf={(row, index) => String(row.id ?? index)}
          columns={[
            { key: "title", label: "Вакансия" },
            { key: "status", label: "Статус", render: (row) => statusLabel(row.status) },
            { key: "level", label: "Уровень", render: (row) => String(row.level ?? "—") },
            { key: "question_count", label: "Вопросов" },
          ]}
        />
      );
      break;
    case "list_candidates":
      view = (
        <Table
          rows={asArray(result)}
          keyOf={(row, index) => String(row.id ?? index)}
          columns={[
            { key: "full_name", label: "Кандидат" },
            { key: "email", label: "E-mail" },
            { key: "interview_count", label: "Интервью" },
            {
              key: "last_interview_status",
              label: "Последний статус",
              render: (row) => statusLabel(row.last_interview_status),
            },
          ]}
        />
      );
      break;
    case "ranking": {
      const rows = result && typeof result === "object" ? asArray((result as Record<string, unknown>).rows) : [];
      view = (
        <Table
          rows={rows}
          keyOf={(row, index) => String(row.interview_id ?? index)}
          columns={[
            { key: "rank", label: "#" },
            {
              key: "candidate_name",
              label: "Кандидат",
              render: (row) => String(row.candidate_name ?? row.full_name ?? "—"),
            },
            {
              key: "fit_score",
              label: "Балл",
              render: (row) => (typeof row.fit_score === "number" ? row.fit_score.toFixed(1) : "—"),
            },
            {
              key: "recommendation",
              label: "Рекомендация",
              render: (row) => recommendationLabel(row.recommendation),
            },
            { key: "status", label: "Статус", render: (row) => statusLabel(row.status) },
            { key: "decision", label: "Решение", render: (row) => decisionLabel(row.decision ?? null) },
          ]}
        />
      );
      break;
    }
    case "list_members":
      view = (
        <Table
          rows={asArray(result)}
          keyOf={(row, index) => String(row.user_id ?? row.id ?? index)}
          columns={[
            { key: "full_name", label: "Участник", render: (row) => String(row.full_name || row.email || "—") },
            { key: "role", label: "Роль" },
            { key: "is_active", label: "Активен", render: (row) => (row.is_active === false ? "нет" : "да") },
            {
              key: "last_login_at",
              label: "Последний вход",
              render: (row) =>
                typeof row.last_login_at === "string" ? new Date(row.last_login_at).toLocaleDateString("ru-RU") : "—",
            },
          ]}
        />
      );
      break;
    case "check_models":
      view = (
        <Table
          rows={asArray(result)}
          keyOf={(row, index) => String(row.role ?? index)}
          columns={[
            { key: "role", label: "Роль" },
            { key: "model", label: "Модель" },
            {
              key: "ok",
              label: "Статус",
              render: (row) => (row.ok === true || row.status === "ok" ? "ок" : String(row.error ?? row.status ?? "—")),
            },
            {
              key: "latency_ms",
              label: "Задержка",
              render: (row) => (typeof row.latency_ms === "number" ? `${row.latency_ms} мс` : "—"),
            },
          ]}
        />
      );
      break;
    default:
      view = null;
  }
  return (
    <div className="mt-2 space-y-2">
      {view}
      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
          Показать данные
        </summary>
        <pre className="thin-scrollbar mt-2 max-h-64 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] leading-snug">
          {json.length > 4000 ? `${json.slice(0, 4000)}…` : json}
        </pre>
      </details>
    </div>
  );
}
