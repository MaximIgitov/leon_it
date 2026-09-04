# Сквозные тесты

Playwright прогоняет сценарий кандидата целиком — ссылка, согласия, проверка
камеры, тренировочный вопрос, запись двух ответов на фейковую камеру Chromium,
завершение — и проверяет, что рекрутер видит ответы в карточке.

## Запуск локально

```bash
cd e2e
npm install
npm run install-browsers
npm test
```

`global-setup.ts` сам поднимает бэкенд (SQLite во временном каталоге,
`MODEL_PROVIDER=fake`, письма в консоль), воркер задач и фронтенд (`next dev`),
а после прогона останавливает их. Нужны `uv` (на Windows — `python -m uv`,
переопределяется `UV_BIN`) и установленные зависимости `backend/` и `frontend/`.

Против уже запущенного стенда: `E2E_EXTERNAL=1 E2E_BASE_URL=https://… E2E_API_URL=https://…/api npm test`.

`E2E_VIDEO=1` пишет видео каждого сценария в `test-results/` — из него
собирается демо для лендинга.

## Проекты

| Проект | Что проверяет |
|---|---|
| `chromium` | сквозной путь кандидата и регрессия кабинета рекрутера на десктопе |
| `mobile-chrome` | тот же путь кандидата на профиле Pixel 7: узкий экран, касания |

```bash
npm run test:desktop      # только десктоп
npm run test:mobile       # только мобильный профиль
```

Сценарий `recruiter-flow.spec.ts` заполняет интервью через API (`completeInterview`),
поэтому не зависит от камеры: он про кабинет — заключение, вкладку достоверности,
решение, ссылку для нанимающего менеджера и дашборд.

## Демо-видео для лендинга

```bash
E2E_VIDEO=1 npx playwright test --project=chromium candidate-flow
```

Playwright положит записи в `test-results/**/video.webm`. Файл лучшего прогона
конвертируется и кладётся в `frontend/public/demo/interview-demo.mp4`:

```bash
ffmpeg -i test-results/**/video.webm -vf "scale=1280:-2,fps=24"   -c:v libx264 -crf 30 -preset slow -movflags +faststart -an   ../frontend/public/demo/interview-demo.mp4
```

Звук вырезается (`-an`): в фейковой камере его нет, а лишняя дорожка только
утяжеляет файл. Лендинг подхватывает видео автоматически; пока файла нет,
показывается заглушка с постером.

Для записи нужен ffmpeg из дистрибутива Playwright: `npx playwright install ffmpeg`.

## В CI

Job `e2e` в `.github/workflows/ci.yml` запускается на `main` и не блокирует
слияние: цель — регрессия и запись демо, а не ворота PR.
