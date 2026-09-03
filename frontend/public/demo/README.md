# Видеодемо для лендинга

Лендинг (`src/components/landing/video-demo.tsx`) показывает ролик
`interview-demo.mp4` из этого каталога. Файла в репозитории нет — пока его
нет, вместо плеера рендерится заглушка «Демо появится после записи».
Наличие файла проверяется на сервере через `fs.existsSync` при рендере
страницы; главная статическая, поэтому ролик должен лежать здесь **до**
`npm run build` (в Docker-образ каталог `public/` копируется целиком).

## Как записать

Ролик пишет Playwright-сценарий кандидата с фейковой камерой Chromium
(`e2e/tests/candidate-flow.spec.ts`): ссылка → согласия → проверка камеры →
тренировочный вопрос → ответы с таймером → «Спасибо, интервью завершено!».

```bash
cd e2e
npm install && npm run install-browsers
E2E_VIDEO=1 npm test            # Windows PowerShell: $env:E2E_VIDEO=1; npm test
```

Видео каждого сценария появится в `e2e/test-results/<имя теста>/video.webm`
(1280×800, нужен ffmpeg из дистрибутива Playwright). Переложите его в mp4,
чтобы играло в Safari, и положите сюда:

```bash
ffmpeg -i e2e/test-results/<...>/video.webm \
  -c:v libx264 -pix_fmt yuv420p -crf 26 -preset slow -movflags +faststart -an \
  frontend/public/demo/interview-demo.mp4
```

Ориентиры: до 10 МБ, без звука (в сценарии его нет), кадр 1280×800.
`poster.svg` — постер плеера, он же основа заглушки; менять не обязательно.
