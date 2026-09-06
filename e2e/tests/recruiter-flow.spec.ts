import { expect, test } from "@playwright/test";

import { completeInterview, getInterview, seedInterview } from "./api";

/*
 * Регрессия кабинета: рекрутер проходит путь после интервью — карточка с
 * отчётом, вкладка проверки записи, решение, ссылка для нанимающего
 * менеджера и дашборд. Интервью заполняется через API (кандидатский путь
 * проверяет candidate-flow), поэтому сценарий быстрый и не зависит от камеры.
 */

async function login(page: import("@playwright/test").Page, email: string, password: string) {
  // Ждём гидратацию: в WebKit форма оживает позже, и ввод до неё теряется.
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  // Обзор должен дорисоваться и дозапросить данные до следующего goto: если
  // прервать клиентский переход роутера на середине, он может отменить нашу
  // навигацию (заметно в WebKit). networkidle здесь не помогает: он относится
  // к документу /login.
  await expect(page.getByRole("heading", { name: "Приглашено" })).toBeVisible();
  await expect(page.getByText("Воронка", { exact: true })).toBeVisible();
  await page.waitForTimeout(750);
}

/**
 * Полная навигация после клиентского перехода. Роутер может ответить на
 * прерванный fetch жёстким переходом на текущую страницу («interrupted by
 * another navigation», воспроизводится в WebKit) — тогда дожидаемся его и
 * повторяем переход один раз.
 */
async function gotoSettled(page: import("@playwright/test").Page, url: string) {
  try {
    await page.goto(url);
  } catch (error) {
    if (!String(error).includes("interrupted by another navigation")) throw error;
    await page.waitForLoadState("load");
    await page.goto(url);
  }
}

test("рекрутер работает с заключением, достоверностью и доступом", async ({ page, context }) => {
  const seed = await seedInterview();
  await completeInterview(seed);
  await expect
    .poll(async () => (await getInterview(seed)).status, { timeout: 60_000 })
    .toBe("evaluated");

  await login(page, seed.email, seed.password);

  // Ранжирование по вакансии: кандидат с баллом и рекомендацией.
  await gotoSettled(page, `/vacancies/${seed.vacancyId}`);
  await expect(page.getByRole("heading", { name: "Python-разработчик" })).toBeVisible();

  await gotoSettled(page, `/vacancies/${seed.vacancyId}/interviews/${seed.interviewId}`);
  await expect(page.getByRole("heading", { name: "Иван Кандидат" })).toBeVisible();

  // Отчёт: общее впечатление и разбор по критериям вакансии.
  await page.getByRole("tab", { name: "Отчёт" }).click();
  await expect(page.getByText("Общее впечатление")).toBeVisible({ timeout: 30_000 });

  // Проверка записи: наблюдений нет, но панель объясняет, что проверялось.
  await page.getByRole("tab", { name: /Проверка записи/ }).click();
  await expect(page.getByRole("heading", { name: "Что проверяет Леон" })).toBeVisible();

  // Решение по кандидату сохраняется и видно в панели.
  await page.getByRole("tab", { name: "Решение и заметки" }).click();
  await page.getByRole("button", { name: /Следующий этап/ }).click();
  await page.getByRole("button", { name: "Сохранить решение" }).click();
  await expect(page.getByText(/Сохранено: Дальше/)).toBeVisible({ timeout: 15_000 });

  // Ссылка для нанимающего менеджера открывается в отдельной вкладке без входа.
  await page.getByRole("tab", { name: "Доступ" }).click();
  await page.getByLabel("Для кого").fill("Тимлид Петров");
  await page.getByRole("button", { name: "Создать ссылку" }).click();
  const link = page.locator("input[readonly]").first();
  await expect(link).toBeVisible({ timeout: 15_000 });
  const url = await link.inputValue();
  expect(url).toContain("/r/");

  const guest = await context.browser()?.newContext({ locale: "ru-RU" });
  if (guest) {
    const guestPage = await guest.newPage();
    await guestPage.goto(url);
    await expect(guestPage.getByRole("heading", { name: "Иван Кандидат" })).toBeVisible();
    await guest.close();
  }

  // Обзор: воронка учитывает завершённое интервью.
  await gotoSettled(page, "/dashboard");
  await expect(page.getByRole("heading", { name: "Завершили интервью" })).toBeVisible({ timeout: 30_000 });
});
