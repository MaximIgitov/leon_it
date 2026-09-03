import { describe, expect, it } from "vitest";

import { describePush, isPushInFlight, type HuntflowPush } from "./huntflow";

function push(overrides: Partial<HuntflowPush>): HuntflowPush {
  return {
    candidate_id: "c1",
    status: "not_pushed",
    interview_id: null,
    huntflow_applicant_id: null,
    huntflow_vacancy_id: null,
    huntflow_status_id: null,
    last_pushed_at: null,
    last_error: null,
    report_share_url: null,
    job: null,
    ...overrides,
  };
}

describe("describePush", () => {
  it("описывает состояния передачи", () => {
    expect(describePush(null)).toBe("не передан");
    expect(describePush(push({ status: "queued" }))).toBe("в очереди");
    expect(describePush(push({ status: "pushing" }))).toBe("передаётся…");
    expect(describePush(push({ status: "pushed", last_pushed_at: null }))).toBe("передан");
    expect(describePush(push({ status: "pushed", last_pushed_at: "2026-09-03T10:00:00Z" }))).toMatch(
      /^передан /,
    );
  });

  it("показывает ошибку и признак повтора из очереди", () => {
    expect(describePush(push({ status: "error", last_error: "Huntflow ответил 400" }))).toBe(
      "ошибка: Huntflow ответил 400",
    );
    const retrying = push({
      status: "error",
      last_error: "таймаут",
      job: { id: "j", status: "queued", attempts: 1, max_attempts: 5, run_after: null, last_error: null },
    });
    expect(describePush(retrying)).toBe("ошибка, будет повтор: таймаут");
  });
});

describe("isPushInFlight", () => {
  it("активна только в очереди и во время передачи", () => {
    expect(isPushInFlight("queued")).toBe(true);
    expect(isPushInFlight("pushing")).toBe(true);
    expect(isPushInFlight("pushed")).toBe(false);
    expect(isPushInFlight("error")).toBe(false);
    expect(isPushInFlight("not_pushed")).toBe(false);
  });
});
