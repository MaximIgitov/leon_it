import { expect, test } from "@playwright/test";

import { completeInterview, getInterview, seedInterview } from "./api";

/*
 * Регрессия кабинета: рекрутер проходит путь после интервью — карточка с
 * заключением, вкладка достоверности, решение, ссылка для нанимающего
 * менеджера и дашборд. Интервью заполняется через API (кандидатский путь
 * проверяет candidate-flow), поэтому сценарий быстрый и не зависит от камеры.
 */

async function login(page: import("@playwright/test").Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

test("рекрутер работает с заключением, достоверностью и доступом", async ({ page, context }) => {
  const seed = await seedInterview();
  await completeInterview(seed);
  await expect
    .poll(async () => (await getInterview(seed)).status, { timeout: 60_000 })
    .toBe("evaluated");

  await login(page, seed.email, seed.password);

  // Ранжирование по вакансии: кандидат с баллом и рекомендацией.
  await page.goto(`/vacancies/${seed.vacancyId}`);
  await expect(page.getByRole("heading", { name: "Python-разработчик" })).toBeVisible();

  await page.goto(`/vacancies/${seed.vacancyId}/interviews/${seed.interviewId}`);
  await expect(page.getByRole("heading", { name: "Иван Кандидат" })).toBeVisible();

  // Заключение: резюме и баллы по компетенциям.
  await page.getByRole("tab", { name: "Заключение" }).click();
  await expect(page.getByText("Компетенции")).toBeVisible({ timeout: 30_000 });

  // Достоверность: наблюдений нет, но панель показывает проверку.
  await page.getByRole("tab", { name: /Достоверность/ }).click();
  await expect(page.getByText("Достоверность записи")).toBeVisible();

  // Решение по кандидату сохраняется и видно в статусе.
  await page.getByRole("tab", { name: "Решение и заметки" }).click();
  await page.getByRole("button", { name: "Дальше", exact: true }).click();
  await expect(page.getByText(/Текущее: Дальше/)).toBeVisible({ timeout: 15_000 });

  // Ссылка для нанимающего менеджера открывается в отдельной вкладке без входа.
  await page.getByRole("tab", { name: "Доступ" }).click();
  await page.getByPlaceholder(/Кому/).fill("Тимлид Петров");
  await page.getByRole("button", { name: "Создать" }).click();
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

  // Дашборд: воронка учитывает завершённое интервью.
  await page.goto("/dashboard");
  await expect(page.getByText("Приглашены")).toBeVisible({ timeout: 30_000 });
});
