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
    const retry = page.getByRole("button", { name: "Проверить снова" });
    if (await retry.isVisible().catch(() => false)) {
      await retry.click();
    }
    try {
      // Кнопка активна, только когда поток камеры и микрофона получен.
      await expect(record).toBeEnabled({ timeout: 8000 });
      break;
    } catch {
      // Фейковая камера иногда не отдаёт поток первому контексту без ошибки:
      // перезагрузка страницы запрашивает устройства заново.
      await page.reload();
      await expect(page.getByRole("heading", { name: "Проверка камеры и микрофона" })).toBeVisible();
    }
  }
  await record.click();
  await expect(page.getByText("Меня видно и слышно")).toBeVisible({ timeout: 20_000 });
  await page.getByText("Меня видно и слышно").click();
  await page.getByRole("button", { name: /Всё готово — к интервью/ }).click();
}

/*
 * Сквозной сценарий кандидата в формате «кнопка ответа»: ссылка → согласия →
 * проверка устройств → тренировочный вопрос → два ответа на камеру →
 * «интервью завершено» → возврат по ссылке. Камера и микрофон — фейковые устройства Chromium, запись
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

/*
 * Живой диалог (формат по умолчанию): после «Начать интервью» вопросы звучат
 * сами, комната слушает без кнопки «Начать ответ». Фейковый микрофон Chromium
 * шумит без пауз, поэтому детектор не завершает ответ сам — завершаем кнопкой,
 * которая в этом формате остаётся страховкой; следующий вопрос должен
 * прозвучать без экрана «Готовы к вопросу?».
 */
test("живой диалог: вопросы звучат сами, кнопка завершает ответ", async ({ page }) => {
  const seed = await seedInterview({ interviewMode: "live", practice: false });

  await page.goto(seed.link);
  await expect(page.getByText(/Живой диалог/)).toBeVisible();
  const checkboxes = page.getByRole("checkbox");
  await checkboxes.nth(0).click();
  await checkboxes.nth(1).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await passDeviceCheck(page);

  // E2E_SHOTS_DIR=<каталог> — сохранить экраны живого диалога (для материалов и ревью вёрстки).
  const shots = process.env.E2E_SHOTS_DIR;
  const start = page.getByRole("button", { name: "Начать интервью" });
  await expect(start).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/live-intro.png` });
  await start.click();
  for (const index of [0, 1]) {
    const finish = page.getByRole("button", { name: "Завершить ответ" });
    await expect(finish).toBeVisible({ timeout: 40_000 });
    await expect(page.getByText(`Вопрос ${index + 1} из 2`)).toBeVisible();
    await page.waitForTimeout(2500);
    if (shots && index === 0) await page.screenshot({ path: `${shots}/live-listening.png` });
    await finish.click();
    await expect(finish).toBeHidden({ timeout: 30_000 });
  }

  await expect(page.getByRole("heading", { name: /Спасибо, интервью завершено/ })).toBeVisible({ timeout: 40_000 });
  await expect.poll(async () => (await getInterview(seed)).status, { timeout: 20_000 }).not.toBe("in_progress");
});
