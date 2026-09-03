#!/usr/bin/env bash
# Выкат стенда. Запускается self-hosted раннером из корня репозитория:
#
#   IMAGE_TAG=<sha> BUILD_ON_SERVER=false deploy/deploy.sh
#
# Обычный путь — образы собраны на GitHub и лежат в GHCR: pull → миграции →
# up. Резервный путь (BUILD_ON_SERVER=true) — когда сборка на GitHub упала
# или образы недоступны: собираем образы прямо на сервере из текущего checkout.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/leonit}"
ENV_FILE="${APP_DIR}/.env"
COMPOSE_FILE="${APP_DIR}/docker-compose.yml"
IMAGE_TAG="${IMAGE_TAG:?IMAGE_TAG is required}"
BACKEND_IMAGE="${BACKEND_IMAGE:-ghcr.io/maximigitov/leon_it/backend}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:-ghcr.io/maximigitov/leon_it/frontend}"
BUILD_ON_SERVER="${BUILD_ON_SERVER:-false}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '[deploy] %s\n' "$*"; }

upsert_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${ENV_FILE}"
  fi
}

[[ -f "${ENV_FILE}" ]] || { log "нет ${ENV_FILE}: сначала bootstrap-server.sh"; exit 1; }

log "устанавливаем compose и Caddyfile в ${APP_DIR}"
install -m 644 "${REPO_DIR}/deploy/docker-compose.yml" "${COMPOSE_FILE}"
install -m 644 "${REPO_DIR}/deploy/Caddyfile" "${APP_DIR}/Caddyfile"

# Секреты, появившиеся после bootstrap: генерируем один раз, дальше не трогаем.
ensure_secret() {
  local key="$1" value="$2"
  grep -qE "^${key}=." "${ENV_FILE}" || { log "генерируем ${key}"; upsert_env "${key}" "${value}"; }
}
# Ключ Fernet для секретов интеграций (OAuth-токены HH.ru и т. п.).
ensure_secret DATA_ENCRYPTION_KEY "$(openssl rand -base64 32 | tr '+/' '-_')"

# Секреты из GitHub (SYNC_<ИМЯ>=значение): непустые переносятся в .env.
while IFS='=' read -r name _; do
  value="${!name}"
  [[ -n "${value}" ]] || continue
  upsert_env "${name#SYNC_}" "${value}"
  log "обновлено ${name#SYNC_} из секретов"
done < <(env | grep -E '^SYNC_[A-Z0-9_]+=' || true)

# Есть ключ модели — стенд работает на реальном провайдере, а не на фейке.
if grep -qE '^MODEL_DEFAULT_API_KEY=.+' "${ENV_FILE}"; then
  upsert_env MODEL_PROVIDER openai_compatible
  upsert_env MODEL_ALLOW_FAKE_IN_PRODUCTION false
fi

upsert_env IMAGE_TAG "${IMAGE_TAG}"
upsert_env BACKEND_IMAGE "${BACKEND_IMAGE}"
upsert_env FRONTEND_IMAGE "${FRONTEND_IMAGE}"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

if [[ "${BUILD_ON_SERVER}" == "true" ]]; then
  log "собираем образы на сервере (резервный путь)"
  # Dockerfile используют BuildKit (RUN --mount=type=cache); legacy builder их
  # не соберёт, поэтому buildx на сервере обязателен (ставит bootstrap).
  export DOCKER_BUILDKIT=1
  docker build --network=host -t "${BACKEND_IMAGE}:${IMAGE_TAG}" "${REPO_DIR}/backend"
  docker build --network=host \
    --build-arg NEXT_PUBLIC_BACKEND_API_URL=/api \
    --build-arg "NEXT_PUBLIC_APP_URL=${PUBLIC_URL}" \
    -t "${FRONTEND_IMAGE}:${IMAGE_TAG}" "${REPO_DIR}/frontend"
else
  log "тянем образы ${IMAGE_TAG}"
  compose pull api frontend
fi

log "поднимаем базу"
compose up -d postgres

log "применяем миграции"
compose run --rm --no-deps api alembic upgrade head

log "поднимаем приложение"
compose up -d --remove-orphans

log "ждём api"
for attempt in $(seq 1 30); do
  if compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=5).read()" >/dev/null 2>&1; then
    break
  fi
  if [[ "${attempt}" == "30" ]]; then
    compose ps
    compose logs --tail=100 api
    exit 1
  fi
  sleep 3
done

log "ждём https://${DOMAIN}"
for attempt in $(seq 1 40); do
  if curl -fsS -m 10 "https://${DOMAIN}/api/health" >/dev/null 2>&1; then
    break
  fi
  if [[ "${attempt}" == "40" ]]; then
    compose logs --tail=60 caddy
    exit 1
  fi
  sleep 5
done

compose ps
log "убираем образы старше недели"
docker image prune -af --filter "until=168h" >/dev/null || true
log "готово: https://${DOMAIN}"
