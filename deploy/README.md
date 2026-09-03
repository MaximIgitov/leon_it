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
