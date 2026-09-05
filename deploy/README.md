# Стенд

Один VPS (Ubuntu, 2 vCPU, 4 ГБ), всё в docker compose: PostgreSQL, API,
фронтенд, Caddy с автоматическим HTTPS. Наружу открыт только Caddy (80/443).

## Первичная подготовка сервера

```bash
scp deploy/bootstrap-server.sh root@<host>:/tmp/
ssh root@<host> 'bash /tmp/bootstrap-server.sh <домен>'
```

Без домена скрипт возьмёт `<ip-через-дефисы>.sslip.io` — этого достаточно
для HTTPS через Let's Encrypt, а без HTTPS браузеры не дают доступ к камере.

## Свой домен

Стенд живёт на `leon-it.tech` (A-записи `leon-it.tech` и `www.leon-it.tech`
указывают на сервер). Переезд на домен — четыре правки в `/opt/leonit/.env`
и `docker compose up -d`, образы пересобирать не нужно:

1. `DOMAIN=<домен>` — по нему Caddy выпускает сертификат, а деплой проверяет
   health; `DOMAIN_ALIASES="www.<домен> <старый-адрес>"` — через пробел и в
   кавычках (`deploy.sh` читает `.env` как shell), Caddy
   получит сертификаты и на них: `www` перенаправляется на основной домен, а
   старый `<ip>.sslip.io` продолжает открывать уже разосланные ссылки.
2. `PUBLIC_URL=https://<домен>` — адрес в письмах, ссылках кандидатов и
   документах согласий; `CORS_ORIGINS` — все хосты списком.
3. `HH_REDIRECT_URL=https://<домен>/api/integrations/hh/callback` — тот же адрес
   нужно вписать в Redirect URI приложения в кабинете разработчика hh.ru.
4. Переменная репозитория `PUBLIC_URL` (Settings → Variables) — с ней
   собирается фронтенд (`NEXT_PUBLIC_APP_URL`: канонические ссылки и
   метаданные лендинга); подхватится на следующем выкате.

Затем на сервере ставится self-hosted раннер GitHub Actions от пользователя
`runner` (он в группе `docker`): токен регистрации — в настройках репозитория
(Settings → Actions → Runners → New self-hosted runner), метка `leonit-vps`.

## Выкат

Каждое слияние в `main` запускает `.github/workflows/deploy.yml`:

1. `build` (GitHub-раннер) собирает образы бэкенда и фронтенда и кладёт их в
   GHCR с тегом коммита.
2. `deploy` (self-hosted раннер) копирует `docker-compose.yml` и `Caddyfile` в
   `/opt/leonit`, тянет образы, применяет миграции, перезапускает сервисы и
   проверяет `https://<домен>/api/health`.

Если сборка на GitHub упала, `deploy` собирает образы на сервере сам
(`BUILD_ON_SERVER=true`). То же можно запустить вручную: Actions → Deploy →
Run workflow → «Собрать образы на сервере».

## Секреты и настройки

- `/opt/leonit/.env` — единственное место с секретами стенда (см.
  `.env.example`). Пайплайн туда только дописывает `IMAGE_TAG`.
- Переменная репозитория `PUBLIC_URL` — публичный адрес, который зашивается во
  фронтенд при сборке.
- Секреты репозитория с теми же именами, что переменные приложения, при выкате
  переносятся в `.env` (список — в `deploy.yml`, шаг «Выкат»): `MODEL_DEFAULT_API_KEY`
  (ключ AI Tunnel; при его наличии стенд автоматически переходит с фейкового
  провайдера на `openai_compatible`), `MODEL_*_MODEL`, `MODEL_DEFAULT_PROXY_URL`,
  `HH_CLIENT_ID` / `HH_CLIENT_SECRET`, `EMAIL_MODE`, `SMTP_*`. Пустой секрет
  ничего не трогает — значения можно задать и прямо в `.env` на сервере.

### HH.ru

Без ключей интеграция работает в демо-режиме на фикстурах — для стенда этого
достаточно. Для настоящего подключения в `/opt/leonit/.env` добавляются:

| Переменная | Значение |
|---|---|
| `HH_CLIENT_ID`, `HH_CLIENT_SECRET` | Ключи приложения с dev.hh.ru (тип «для работодателей»). |
| `HH_REDIRECT_URL` | Необязательно: по умолчанию `${PUBLIC_URL}/api/integrations/hh/callback`; тот же адрес указывается в настройках приложения HH. |
| `HH_MODE` | Необязательно: `auto` (по ключам), `fake`, `real`. |
| `HH_USER_AGENT` | Необязательно: `LeonIT/1.0 (info@napoleonit.ru)` — HH требует контакт в User-Agent. |
| `HH_SYNC_INTERVAL_MINUTES` | Необязательно: период фоновой синхронизации, по умолчанию 10. |

Адрес вебхука с секретом показывается владельцу на странице «Интеграции →
HH.ru»; его вручную регистрируют в уведомлениях приложения HH. Токены
шифруются `DATA_ENCRYPTION_KEY`, поэтому ключ нельзя терять при переносе базы.
Интеграция с Huntflow (токен вводит владелец организации в кабинете и он
хранится в БД зашифрованным `DATA_ENCRYPTION_KEY`; в `.env` только режим):

| Переменная | Значение по умолчанию | Назначение |
|---|---|---|
| `HUNTFLOW_MODE` | `auto` | `auto` — реальный клиент по токену, демо без токена; `fake` — всегда фикстуры (стенд без Huntflow); `real` — демо запрещено. |
| `HUNTFLOW_API_BASE` | `https://api.huntflow.ru/v2` | Адрес API. |
| `HUNTFLOW_TIMEOUT_S` | `15` | Таймаут запроса к Huntflow, секунды. |

## Полезное на сервере

```bash
cd /opt/leonit
docker compose ps
docker compose logs -f api
docker compose exec api alembic current
```
