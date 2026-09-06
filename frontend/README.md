# Leon — фронтенд

Интервью с ИИ для кандидата и кабинет команды: вакансии, кандидаты, отчёты,
интеграции, база знаний и ассистент. API, запись медиа и ML-процессы сохраняют
существующие контракты бэкенда.

Стек из `../ai.crm`: TanStack Start 1.168.30 / Router 1.170.18, React 19.2.4,
Vite 8, Nitro 3, Tailwind CSS 4.2.1 и HeroUI 3.2.3. Node.js 22.12 или новее.

## Запуск

```bash
npm ci
cp .env.example .env.local
npm run dev                  # http://localhost:3000
```

По умолчанию запросы идут на `/api`: в разработке Nitro проксирует их в
`http://127.0.0.1:8000`, в production это делает существующий Caddy. Можно
переопределить адрес через `VITE_BACKEND_API_URL`. Публичный адрес для SEO и
карты сайта задаётся `VITE_APP_URL`. Прежние `NEXT_PUBLIC_BACKEND_API_URL` и
`NEXT_PUBLIC_APP_URL` поддерживаются, в том числе существующими Docker build args.
Это публичные настройки сборки: секреты в них передавать нельзя.

В `.npmrc` задан `legacy-peer-deps=true`, как при сборке референсного проекта:
Tailwind Vite plugin 4.2.1 ещё не включает Vite 8 в peer range. Версии сохранены
как в `ai.crm`; lock-файл фиксирует разрешённые зависимости.

## Сборка и запуск

```bash
npm run typecheck            # генерация дерева маршрутов + TypeScript
npm run build                # генерация маршрутов, TypeScript и production build
npm start                    # http://localhost:3000; PORT можно переопределить
```

`npm run lint` оставлен как совместимый alias проверки TypeScript. Тесты —
vitest (`npm test`): статические компоненты рендерятся через `react-dom/server`,
ссылки роутера в них подменяются обычным `<a>`, потому что TanStack Router
требует контекст роутера.

Docker использует Node 22 и запускает `.output/server/index.mjs`. Порт `3000`,
healthcheck и маршрутизация Caddy остаются совместимыми с `deploy/docker-compose.yml`.

## Устройство

- `src/routes/` — настоящие TanStack routes, metadata, layouts и server routes.
- `src/routeTree.gen.ts` — генерируемое дерево; руками не редактировать.
- `src/router.tsx` — Router, предзагрузка по намерению, восстановление прокрутки и View Transitions.
- `src/app/` — существующие экраны и layout-компоненты, которые подключают routes.
- `src/components/ui/` — HeroUI-компоненты для существующих продуктовых экранов.
- `src/components/interview/` — устройства, пробный вопрос, запись ответов и редактор кода.
- `src/components/reports/` — плеер, ИИ-оценка, решения и отчёты кандидата.
- `src/lib/api/` — прежний API-клиент и контракты, без изменений API/ML.
- `src/lib/router.tsx` — компактная совместимость существующих `href` и navigation hooks с TanStack Router.
- `src/app/globals.css` — тема HeroUI, палитра, шрифты, формы и движение.
- `public/brand/` — логотип и персонажи.

Публичные адреса: `/`, `/practice`, `/login`, `/register`, `/i/:token`, `/r/:token`,
`/join`, `/legal/:slug`, `/unsubscribe/:token`. Кабинет: `/dashboard`, `/vacancies`,
`/vacancies/:id`, `/vacancies/:id/interviews/:interviewId`, `/candidates`,
`/candidates/:id`, `/organization`, `/organization/knowledge`, `/integrations`,
`/integrations/hh`, `/integrations/huntflow`. Адреса приглашений не менялись.

Главная рендерится на сервере и затем гидратируется React. `/robots.txt` и
`/sitemap.xml` обслуживаются server routes; персональные страницы исключены
из индексации. Данные юридических документов продолжает отдавать API.

Проверка устройств и `/practice` используют браузерные media API. Для камеры
и микрофона нужен HTTPS или localhost. Интервью по приглашению сохраняет
текущую отправку видео, аудио, кода, телеметрии и согласий на бэкенд.

## Дизайн

Палитра, типографика, размеры, маскоты и анимации зафиксированы в [docs/DESIGN.md](../docs/DESIGN.md).
Новая тема HeroUI находится в `src/styles/foundation.css`; страницы используют её общие семантические токены.
Публичная тренировка доступна на `/practice`, запись остаётся в браузере.

Для предпросмотра при занятом порту 3000: `npm run dev -- --port 5178 --host 127.0.0.1`.
