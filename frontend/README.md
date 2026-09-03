# LeonIT — фронтенд

Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui. Кабинет рекрутера и
нанимающего менеджера, комната интервью для кандидата, лендинг.

## Запуск

```bash
npm install
cp .env.example .env.local   # адрес бэкенда
npm run dev                  # http://localhost:3000
```

## Проверки

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

## Устройство

```
src/
├── app/            маршруты: (app) — кабинет, остальное — публичные страницы
├── components/
│   ├── brand/      логотип LeonIT
│   ├── dashboard/  плитки, воронка, график по дням (Recharts), разбивки
│   ├── layout/     оболочка кабинета, заголовки страниц
│   └── ui/         shadcn/ui-компоненты
├── hooks/
└── lib/api/        клиент к бэкенду
```

Тема: акцент Napoleon IT `#140AF0`, гарнитура Manrope, светлая и тёмная схемы
через CSS-переменные в `src/app/globals.css`.
