#!/usr/bin/env bash
# One-time server setup for a fresh Ubuntu 22.04/24.04 host, then first start.
#   git clone … && cd 60-onlone/deploy && sudo ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null; then
  echo "→ installing Docker"
  curl -fsSL https://get.docker.com | sh   # behind restrictions: use a mirror, see docs/DEPLOY.md §1
fi

if [ ! -f .env ]; then
  echo "→ creating .env with fresh secrets"
  cp env.production.example .env
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env
  chmod 600 .env
  echo "   ویرایش کنید: nano deploy/.env  (دامنه‌ها، درگاه، کاوه‌نگار، ربات هشدار) و دوباره اجرا کنید."
  exit 0
fi

BACKUP_DIR=$(grep -E '^BACKUP_HOST_DIR=' .env | cut -d= -f2-); BACKUP_DIR=${BACKUP_DIR:-/var/backups/sixty}
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"

# firewall: only SSH and web
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

echo "→ building and starting"
docker compose -f docker-compose.prod.yml --env-file .env up -d --build

echo "→ waiting for the API"
for i in $(seq 1 60); do
  docker compose -f docker-compose.prod.yml exec -T backend python -c \
    "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=3)" 2>/dev/null && break
  sleep 5
done

echo "→ launch preflight (BLOCKER = must fix before opening)"
docker compose -f docker-compose.prod.yml exec -T backend python -m scripts.launch_preflight || true
echo "→ first backup"
docker compose -f docker-compose.prod.yml exec -T backup /bin/sh /backup.sh
echo "done."
