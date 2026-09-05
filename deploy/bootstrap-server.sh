#!/usr/bin/env bash
# Первичная подготовка чистого Ubuntu-сервера под стенд LeonIT. Идемпотентен:
# повторный запуск ничего не ломает. Запускается от root:
#
#   scp deploy/bootstrap-server.sh root@<host>:/tmp/ && ssh root@<host> 'bash /tmp/bootstrap-server.sh <domain>'
#
# Делает: Docker + Compose из репозитория Ubuntu, swap 2 ГБ (на 4 ГБ RAM сборка
# фронтенда иначе падает по памяти), пользователь runner для GitHub Actions,
# каталог /opt/leonit и .env со сгенерированными секретами.
set -euo pipefail

DOMAIN="${1:-}"
APP_DIR=/opt/leonit
ENV_FILE="${APP_DIR}/.env"

log() { printf '[bootstrap] %s\n' "$*"; }

if [[ -z "${DOMAIN}" ]]; then
  ip="$(hostname -I | awk '{print $1}')"
  DOMAIN="${ip//./-}.sslip.io"
  log "домен не задан — используем ${DOMAIN}"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-buildx docker-compose-v2 curl jq git >/dev/null
systemctl enable --now docker >/dev/null
log "docker $(docker --version | awk '{print $3}') готов"

if ! swapon --show | grep -q '/swapfile'; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
  log "swap 2G включён"
fi
sysctl -w vm.swappiness=10 >/dev/null
mkdir -p /etc/sysctl.d
echo 'vm.swappiness=10' >/etc/sysctl.d/90-leonit.conf

id runner >/dev/null 2>&1 || useradd -m -s /bin/bash runner
usermod -aG docker runner
mkdir -p "${APP_DIR}/data"
chown -R runner:runner "${APP_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  log "создаём ${ENV_FILE}"
  cat >"${ENV_FILE}" <<EOF
DOMAIN=${DOMAIN}
# Дополнительные хосты через пробел и в кавычках (www.<домен>, старый sslip-адрес).
DOMAIN_ALIASES=""
ACME_EMAIL=admin@${DOMAIN}
PUBLIC_URL=https://${DOMAIN}
CORS_ORIGINS=["https://${DOMAIN}"]

POSTGRES_DB=leonit
POSTGRES_USER=leonit
POSTGRES_PASSWORD=$(openssl rand -hex 24)

JWT_SECRET=$(openssl rand -hex 32)
DATA_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
METRICS_TOKEN=$(openssl rand -hex 16)
LOG_LEVEL=INFO

IMAGE_TAG=latest
EOF
  chown runner:runner "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
fi

log "готово: стенд будет доступен на https://${DOMAIN} после первого деплоя"
