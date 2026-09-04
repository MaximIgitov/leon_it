import { expect, test, type Page } from "@playwright/test";

import { getInterview, seedInterview } from "./api";

/**
 * Экран проверки устройств: фейковая камера Chromium обычно доступна сразу, но
 * второй контекст браузера иногда не получает поток с первой попытки — тогда
 * комната показывает «Камера или микрофон не найдены» и кнопку «Проверить снова».
 * Повторяем проверку, прежде чем считать прогон упавшим.
 */
async function passDeviceCheck(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Проверка камеры и микрофона" })).toBeVisible();
  const record = page.getByRole("button", { name: /Записать 5 секунд/ });
  for (let attempt = 0; attempt < 4; attempt += 1) {
    if (await record.isVisible().catch(() => false)) break;
    const retry = page.getByRole("button", { name: "Проверить снова" });
    if (await retry.isVisible().catch(() => false)) {
      await retry.click();
    }
    await page.waitForTimeout(1500);
  }
  await record.click();
  await expect(page.getByText("Меня видно и слышно")).toBeVisible({ timeout: 20_000 });
  await page.getByText("Меня видно и слышно").click();
  await page.getByRole("button", { name: /Всё готово — к интервью/ }).click();
}

/*
 * Сквозной сценарий кандидата: ссылка → согласия → проверка устройств →
 * тренировочный вопрос → два ответа на камеру → «интервью завершено» →
 * возврат по ссылке. Камера и микрофон — фейковые устройства Chromium, запись
 * настоящая (WebM). Кабинет рекрутера проверяет recruiter-flow.spec.ts: там
 * интервью заполняется через API, поэтому один прогон не зависит от того,
 * отдаст ли браузер фейковую камеру второму контексту.
 */
test("кандидат проходит интервью от ссылки до завершения", async ({ page }) => {
  const seed = await seedInterview();

  await page.goto(seed.link);
  await expect(page.getByRole("heading", { name: /Видеоинтервью: Python-разработчик/ })).toBeVisible();
  await expect(page.getByText("2 вопр.")).toBeVisible();

  // Согласия: имя и e-mail подставлены из приглашения, два обязательных чекбокса.
  await expect(page.getByLabel("Имя и фамилия")).toHaveValue("Иван Кандидат");
  const checkboxes = page.getByRole("checkbox");
  await checkboxes.nth(0).click();
  await checkboxes.nth(1).click();
  await page.getByRole("button", { name: "Продолжить" }).click();

  // Проверка устройств: фейковая камера даёт поток; пробная запись 5 с.
  await passDeviceCheck(page);

  // Тренировочный вопрос можно пропустить.
  await page.getByRole("button", { name: "Пропустить" }).click();

  for (const index of [0, 1]) {
    await expect(page.getByText(`Готовы к вопросу ${index + 1}?`)).toBeVisible();
    await page.getByRole("button", { name: "Показать вопрос" }).click();
    // Подготовка 2 с, потом запись стартует сама; ждём и завершаем ответ.
    await expect(page.getByRole("button", { name: "Завершить ответ" })).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(3000);
    await page.getByRole("button", { name: "Завершить ответ" }).click();
    await expect(page.getByText("Ответ сохранён.")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: index === 0 ? "Следующий вопрос" : "Завершить интервью" }).click();
  }

  await expect(page.getByRole("heading", { name: /Спасибо, интервью завершено/ })).toBeVisible();
  await expect.poll(async () => (await getInterview(seed)).status, { timeout: 20_000 }).not.toBe("in_progress");

  // Возврат по ссылке после завершения показывает финальную страницу.
  await page.goto(seed.link);
  await expect(page.getByRole("heading", { name: /Интервью уже завершено/ })).toBeVisible();
});
