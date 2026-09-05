# Runbook стенда LeonIT

Как поднять, выкатить, проверить и починить стенд. Для разработки — `backend/README.md`
и `frontend/README.md`, для плана — `ROADMAP.md`.

## Адреса и доступ

| Что | Где |
|---|---|
| Стенд | `https://89-23-117-80.sslip.io` (Caddy, TLS от Let's Encrypt по домену `<ip-через-дефисы>.sslip.io`) |
| API | `https://89-23-117-80.sslip.io/api`, health — `/api/health`, готовность — `/api/ready` |
| Документация публичного API | `/api/docs/api` (Scalar), спецификация — `/api/openapi.json` |
| Сервер | `ssh root@89.23.117.80`, приложение в `/opt/leonit`, раннер GitHub Actions в `/opt/actions-runner` |
| Образы | `ghcr.io/maximigitov/leon_it/backend`, `ghcr.io/maximigitov/leon_it/frontend` |

Compose-сервисы: `postgres`, `api` (uvicorn), `worker` (очередь задач), `frontend`
(Next.js standalone), `caddy`. Данные: том PostgreSQL и `/data/media` (видео, аудио,
ремуксы) — оба переживают пересборку образов.

## Выкат

1. **Обычный путь** — merge в `main` → `deploy.yml`: сборка образов на GitHub → GHCR →
   self-hosted раннер на сервере запускает `deploy/deploy.sh` (устанавливает
   compose/Caddyfile, дописывает секреты из GitHub в `.env`, `alembic upgrade head`,
   `compose up -d`, ждёт `/api/ready` и `https://<домен>/api/health`).
2. **Резервный путь** — если сборка на GitHub недоступна: `Actions → Deploy → Run
   workflow` с флагом `build_on_server` (образы собираются на сервере из checkout).
3. **Вручную на сервере**:

   ```bash
   cd /opt/leonit && IMAGE_TAG=latest BUILD_ON_SERVER=true bash /opt/actions-runner/_work/leon_it/leon_it/deploy/deploy.sh
   ```

Первичная подготовка нового сервера — `deploy/bootstrap-server.sh` (Docker, раннер,
`.env` со сгенерированными секретами), подробности в `deploy/README.md`.

## Секреты и настройки

Единственное место секретов стенда — `/opt/leonit/.env`. Пайплайн выката дописывает
туда непустые секреты репозитория (шаг «Выкат» в `deploy.yml`): `MODEL_DEFAULT_API_KEY`
(AI Tunnel — при его наличии стенд автоматически переходит с фейкового провайдера на
`openai_compatible`), `MODEL_*_MODEL`, `MODEL_DEFAULT_PROXY_URL`, `HH_CLIENT_ID` /
`HH_CLIENT_SECRET`, `EMAIL_MODE`, `SMTP_*`. Пустой секрет ничего не перезаписывает.

Ключевые переменные (все — в `backend/leonit/core/config.py`):

| Группа | Переменные | Заметки |
|---|---|---|
| Базовые | `ENVIRONMENT=production`, `PUBLIC_URL`, `CORS_ORIGINS`, `JWT_SECRET`, `DATA_ENCRYPTION_KEY` | в production обязательны, генерирует bootstrap/deploy |
| Модели | `MODEL_PROVIDER`, `MODEL_DEFAULT_BASE_URL` (по умолчанию `https://api.aitunnel.ru/v1`), `MODEL_DEFAULT_API_KEY`, `MODEL_<ROLE>_*` для ролей `evaluator`, `assistant`, `interviewer`, `stt`, `tts` | без ключа в production нужен `MODEL_ALLOW_FAKE_IN_PRODUCTION=true` (фейк — только для демо контура) |
| Письма | `EMAIL_MODE=console|smtp`, `EMAIL_FROM`, `SMTP_HOST/PORT/USER/PASSWORD/STARTTLS` | в `console` письма видны во вкладке «Письма» и в логах |
| Медиа | `MEDIA_ROOT=/data/media`, `FFMPEG_BIN`, `FFMPEG_TIMEOUT_S`, `RETENTION_PURGE_HOUR_UTC`, `PIPELINE_STALE_PROCESSING_S` | срок хранения — настройка организации `retention_days` |
| Наблюдаемость | `LOG_LEVEL`, `METRICS_TOKEN` | `/api/metrics` открыт только с токеном |
| Интеграции | `HH_*`, `HUNTFLOW_*`, `CODE_RUNNER*` | без ключей работают в fake/выключенном режиме |
| ИИ-аватар | `AVATAR_ENABLED=true`, `AVATAR_PROVIDER=heygen`, `AVATAR_HEYGEN_API_KEY`; необязательные `AVATAR_HEYGEN_AVATAR_ID`, `AVATAR_HEYGEN_VOICE_ID`, `AVATAR_HEYGEN_ENGINE`, `AVATAR_MAX_TEXT_CHARS` | кошелёк pay-as-you-go HeyGen; без ключа комната показывает персону LeonIT; включается отдельно у каждой вакансии |

Ротация ключа шифрования: новый ключ в `DATA_ENCRYPTION_KEY`, старый — в
`DATA_ENCRYPTION_KEYS_SECONDARY` (через запятую); расшифровка пробует все ключи.

## ИИ-аватар (HeyGen)

Аватар платный (движок `avatar_iii` — около $1 за минуту готового видео),
поэтому включается в два шага: ключ и флаги на сервере (таблица выше) и
переключатель «ИИ-аватар интервьюера» в настройках конкретной вакансии.
Клипы вопросов рендерятся задачей `avatar.prewarm` при публикации, при
смене вопросов или голоса, кэшируются по тексту и голосу и лежат в
`MEDIA_ROOT/avatar/heygen/`. Кандидат никогда не ждёт рендера: если клипа
нет, комната показывает персону LeonIT с озвучкой и ставит прогрев.
Результат задачи (таблица `jobs`, столбец `result`, и лог воркера
`avatar.prewarm`) содержит `rendered/cached/failed` и `balance_usd` — остаток
кошелька после прогрева. Проверить баланс вручную:

```bash
curl -s -H "x-api-key: $AVATAR_HEYGEN_API_KEY" https://api.heygen.com/v3/users/me
```

Публичные образы и голоса: `GET /v3/avatars/looks?ownership=public&avatar_type=studio_avatar`
и `GET /v3/voices?language=Russian` с тем же заголовком. Повтор запроса на тот же
текст идёт с `Idempotency-Key`, поэтому сбой сети не списывает деньги дважды.

## Диагностика

```bash
cd /opt/leonit
docker compose ps                     # все сервисы healthy?
docker compose logs -f --tail=200 api # запросы, ошибки провайдеров
docker compose logs -f --tail=200 worker
docker compose exec api alembic current
curl -fsS https://89-23-117-80.sslip.io/api/health
curl -fsS -H "Authorization: Bearer $METRICS_TOKEN" https://89-23-117-80.sslip.io/api/metrics | head
```

Проверка моделей по ролям (реальный запрос к провайдеру, без сохранения):

```bash
docker compose exec api python -m leonit.ai.diagnostics
```

Логи структурные, с `request_id`; ошибки провайдеров помечены ролью и моделью.
Breaker на провайдера: после серии ошибок роль временно недоступна — это видно в
логах как `circuit open`, восстанавливается сам.

## Очередь задач

Таблица `jobs` в PostgreSQL, воркер — сервис `worker`. Виды задач: `answer.process`
(медиа-пайплайн, ресурс `ffmpeg`), `interview.process` (оценка, ресурс `llm`),
`retention.purge` (чистка медиа), письма, синхронизации интеграций. Аренда задачи
продлевается heartbeat-ом; задача убитого воркера возвращается в очередь по
истечении аренды. Раз в час тик воркера страхует расписание чистки и возвращает в
очередь ответы, брошенные в `processing`.

| Симптом | Что сделать |
|---|---|
| Ответ висит в «обрабатывается» | подождать до `PIPELINE_STALE_PROCESSING_S` (30 мин) — тик вернёт его в очередь; либо перезапустить воркер: `docker compose restart worker` |
| Оценка не появляется | `docker compose logs worker | grep evaluation` — ошибка провайдера пишется в заключение (`status=failed`); кнопка «Переобработать» в карточке кандидата |
| Нет транскрипта, ошибка ffmpeg | текст ошибки в карточке ответа (пути сервера скрыты); проверить `docker compose exec worker ffmpeg -version` |
| Оценка падает с `payment required (HTTP 402)` | баланс агрегатора ниже прогноза цены запроса — пополнить баланс. Прогноз считается по `max_tokens`; лимит по ролям задан в `leonit.ai.config` (оценщик 8192, ассистент 4096, интервьюер 1024) и переопределяется `MODEL_<ROLE>_MAX_TOKENS` |
| Медиа не удаляется по сроку | `docker compose exec worker python -m leonit.pipeline.purge --dry-run` покажет, что попадёт под чистку |

## Медиа и срок хранения

Видео хранится как записал браузер (`/data/media/interviews/<id>/`), рядом — аудио
для STT и ремукс для перемотки. Срок хранения — настройка организации; чистка
ежедневно в `RETENTION_PURGE_HOUR_UTC`, удаляет только файлы, транскрипты и
заключения остаются. Ручной запуск: `python -m leonit.pipeline.purge [--dry-run]`.

## Оценка и eval-контур

Согласие ИИ-оценщика с экспертом измеряется скриптом на датасете
(`backend/evals/`, цель ≥ 80 %):

```bash
cd backend && uv run python evals/eval_agreement.py --json evals/last-run.json
uv run python evals/eval_agreement.py --strict     # код 1, если цель не достигнута
```

Нужны ключи модели-оценщика (`MODEL_EVALUATOR_API_KEY` или `MODEL_DEFAULT_API_KEY`);
с фейковым провайдером скрипт лишь проверяет контур. Пороги рекомендации —
`EVAL_FIT_THRESHOLD` / `EVAL_NO_FIT_THRESHOLD`, действуют на новые оценки.

## Сквозные тесты

Локально (нужны `uv`, зависимости `backend/` и `frontend/`, браузер Playwright или
системный Chrome):

```bash
cd e2e && npm install && npm run install-browsers && npm test
```

Без доступа к CDN Playwright — на системном Chrome:

```bash
cd e2e && E2E_CHANNEL=chrome E2E_FRONTEND_START=1 npm test
```

Против стенда: `E2E_EXTERNAL=1 E2E_BASE_URL=https://… E2E_API_URL=https://…/api npm test`.
В CI job `E2E (кандидат)` запускается на `main` и не блокирует слияние.

Другие движки — по флагам, после `npx playwright install firefox webkit`:
`E2E_FIREFOX=1 npx playwright test --project=firefox` (оба сценария, камера
через prefs) и `E2E_WEBKIT=1 npx playwright test --project=webkit` (только
кабинет: сборка WebKit для Windows не даёт `getUserMedia`, на macOS/Linux
можно снять `testMatch`). Сборка Firefox от Playwright на Windows иногда
приходит без манифеста `mozglue` («side-by-side configuration is incorrect»)
— помогает `npx playwright install --force firefox` или другая версия
Playwright.

## Чек-лист браузеров для комнаты интервью

Комната требует безопасный контекст (HTTPS), `getUserMedia` и `MediaRecorder`.

| Платформа | Браузер | Статус | Заметки |
|---|---|---|---|
| Windows / macOS / Linux | Chrome, Edge (актуальные) | основной | WebM (VP8/Opus), ремукс для перемотки |
| Windows / macOS / Linux | Firefox (актуальный) | поддерживается | WebM; при отказе в разрешении — «Проверить снова» переспрашивает |
| macOS | Safari 14.1+ | поддерживается | MP4 (H.264/AAC); аудио перекодируется в Opus для STT |
| iOS / iPadOS | Safari 15+ | поддерживается | только Safari; озвучка и отсчёт стартуют по клику (автовоспроизведение ограничено); при уходе с вкладки запись ставится на паузу |
| Android | Chrome (актуальный) | поддерживается | фронтальная камера по умолчанию (`facingMode`), wakeLock от засыпания |
| Любая | встроенные браузеры мессенджеров, старые версии | не поддерживается | экран проверки предлагает открыть ссылку в обычном браузере |

Что проверить перед демо: разрешения камеры и микрофона в системе (macOS: Настройки →
Конфиденциальность), уровень микрофона на экране проверки, тренировочный вопрос
пишется и воспроизводится, ответ докачивается после обрыва сети (закрыть вкладку во
время загрузки и вернуться по той же ссылке).

## Типичные сбои

| Сбой | Причина / решение |
|---|---|
| Загрузка в базу знаний отвечает 422 «Формат … не поддерживается» или «не нашлось текста» | сканы и картинки не распознаются: нужен текстовый PDF, docx или текст; лимит файла 20 МБ |
| `curl https://…/api/health` — таймаут, `docker compose logs caddy` ругается на TLS | ACME не выдал сертификат (лимиты Let's Encrypt, порт 80/443 закрыт) — проверить `ufw`, подождать; Caddy повторяет сам |
| API не стартует: `ValueError: … must be set in production` | в `.env` нет `JWT_SECRET`/`DATA_ENCRYPTION_KEY`/`CORS_ORIGINS` — `deploy.sh` генерирует ключ шифрования, остальное из bootstrap |
| API не стартует: `MODEL_PROVIDER=fake is not allowed in production` | добавить `MODEL_DEFAULT_API_KEY` (секрет репозитория или `.env`) либо `MODEL_ALLOW_FAKE_IN_PRODUCTION=true` для демо без моделей |
| Провайдер отвечает 429/5xx, оценки в `failed` | очередь повторяет с паузой; после восстановления — «Переобработать» по интервью |
| Сборка на GitHub падает (лимиты, реестр) | `Run workflow` с `build_on_server`; раннер соберёт образы локально |
| Раннер offline | `systemctl status actions.runner.*` на сервере; переустановка — `deploy/bootstrap-server.sh` |
| В комнате «камера не найдена» на фейковых устройствах (e2e) | Chrome иногда не отдаёт фейковую камеру второму контексту — перезапуск прогона |
