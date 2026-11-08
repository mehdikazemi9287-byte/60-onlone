#!/usr/bin/env bash
# Safe in-place upgrade of the existing SQLite + nginx deployment on 60online-prod
# (the stack in /opt/60online, data in /srv/60online/data) to the code in this checkout.
#
#   sudo bash deploy/sqlite-upgrade.sh stage      # test new code on a COPY of the live DB (ports 8100/3100); live site untouched
#   sudo bash deploy/sqlite-upgrade.sh switch     # fresh backup, stop old stack, start new code on the live DB (ports 8000/3000)
#   sudo bash deploy/sqlite-upgrade.sh rollback   # stop new stack, restore the pre-switch DB copy, start the old stack again
#   sudo bash deploy/sqlite-upgrade.sh status
#
# nginx is not touched: it keeps proxying 127.0.0.1:3000 (frontend) and :8000 (backend).
# Production DB is never modified by "stage". "switch" and "rollback" need explicit owner approval (AGENTS.md rule 11).
set -euo pipefail

NEW="$(cd "$(dirname "$0")/.." && pwd)"
OLD=/opt/60online
LIVE=/srv/60online/data
STAGE=/srv/60online-stage/data
BK=/root/backups-60online
ENV_FILE="$OLD/secrets/backend.env"
TS=$(date +%Y%m%d-%H%M)

need() { [ -f "$ENV_FILE" ] || { echo "!! $ENV_FILE not found"; exit 1; }; }

# compose file for a stack: $1=project $2=data dir $3=backend port $4=frontend port
write_compose() {
  cat >"$NEW/deploy/.compose-$1.yml" <<YML
name: $1
services:
  backend:
    build: $NEW/backend
    env_file: $ENV_FILE
    environment:
      APP_ENV: staging
      SEED_ON_START: "0"
      DATABASE_URL: sqlite:////data/70online.db
      MEDIA_ROOT: /data/admin-media
      DOCUMENT_STORAGE_DIR: /data/documents
      PORT: "8000"
      RATE_LIMIT_PER_MINUTE: "120"
      TRUSTED_PROXY_HOPS: "1"
      CORS_ORIGINS: https://60online.ir,https://www.60online.ir
    volumes: ["$2:/data"]
    ports: ["127.0.0.1:$3:8000"]
    restart: always
    tmpfs: [/tmp]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 768m
  frontend:
    build:
      context: $NEW/frontend
      args: { NEXT_PUBLIC_API_URL: "", NEXT_PUBLIC_MAIN_SITE: "https://60online.ir" }
    environment:
      NODE_ENV: production
      BACKEND_INTERNAL_URL: http://backend:8000
    ports: ["127.0.0.1:$4:3000"]
    depends_on: { backend: { condition: service_healthy } }
    restart: always
    security_opt: ["no-new-privileges:true"]
    mem_limit: 768m
YML
  echo "$NEW/deploy/.compose-$1.yml"
}

counts() {  # row counts of key tables in a sqlite file
  python3 - "$1" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
names = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
for t in ("products", "offers", "suppliers", "orders", "users", "organizations"):
    if t in names:
        print(f"  {t:14s} {c.execute(f'select count(*) from {t}').fetchone()[0]}")
for t in ("schema_migrations", "schema_version", "_migrations"):
    if t in names:
        print(f"  {t}: {c.execute(f'select count(*) from {t}').fetchone()[0]} rows")
PY
}

wait_health() {  # $1=port
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$1/api/v1/health" >/dev/null 2>&1 && { echo "  backend :$1 healthy"; return 0; }
    sleep 5
  done
  echo "!! backend :$1 not healthy"; return 1
}

snapshot() {  # consistent copy of the live DB (sqlite online backup) + media
  mkdir -p "$BK/$TS" && chmod 700 "$BK"
  python3 -c "import sqlite3;s=sqlite3.connect('$LIVE/70online.db');d=sqlite3.connect('$BK/$TS/70online.db');s.backup(d);d.close();s.close()"
  cp -a "$LIVE/admin-media" "$BK/$TS/" 2>/dev/null || true
  echo "  backup: $BK/$TS"
}

case "${1:-status}" in
  stage)
    need
    echo "== 1. copy live DB to $STAGE"
    rm -rf "$STAGE" && mkdir -p "$STAGE"
    python3 -c "import sqlite3;s=sqlite3.connect('$LIVE/70online.db');d=sqlite3.connect('$STAGE/70online.db');s.backup(d);d.close();s.close()"
    cp -a "$LIVE/admin-media" "$STAGE/" 2>/dev/null || true
    chown -R 10001:10001 "$(dirname "$STAGE")"
    echo "== before (copy):"; counts "$STAGE/70online.db"
    echo "== 2. build + start new code on ports 8100/3100"
    F=$(write_compose sixtystage "$STAGE" 8100 3100)
    docker compose -f "$F" up -d --build
    wait_health 8100
    echo "== 3. after migrations:"; counts "$STAGE/70online.db"
    docker compose -f "$F" logs --tail 15 backend
    for p in /api/v1/health/ready /api/v1/products; do
      printf '  %-40s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8100$p")"
    done
    printf '  %-40s %s\n' "frontend /" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3100/)"
    echo "== stage done. Live site untouched. Next (after approval): bash $0 switch"
    ;;
  switch)
    need
    echo "== 1. fresh backup of live DB"; snapshot
    echo "== 2. stop stage + old stack"
    [ -f "$NEW/deploy/.compose-sixtystage.yml" ] && docker compose -f "$NEW/deploy/.compose-sixtystage.yml" down || true
    (cd "$OLD" && docker compose down)
    echo "== 3. start new code on live DB (8000/3000)"
    F=$(write_compose sixty "$LIVE" 8000 3000)
    docker compose -f "$F" up -d --build
    wait_health 8000 || { echo "!! failed — run: bash $0 rollback"; exit 1; }
    counts "$LIVE/70online.db"
    echo "$TS" > "$BK/last-switch"
    echo "== switched. If anything looks wrong: bash $0 rollback"
    ;;
  rollback)
    TSB=$(cat "$BK/last-switch")
    echo "== restore DB from $BK/$TSB and start old stack"
    docker compose -f "$NEW/deploy/.compose-sixty.yml" down || true
    mkdir -p "$BK/failed-$TS" && mv "$LIVE"/70online.db* "$BK/failed-$TS/"
    cp -a "$BK/$TSB/70online.db" "$LIVE/" && chown 10001:10001 "$LIVE/70online.db"
    (cd "$OLD" && docker compose up -d)
    wait_health 8000
    ;;
  status)
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    df -h / | tail -1; free -h | sed -n 2p
    echo "live:"; counts "$LIVE/70online.db"
    [ -f "$STAGE/70online.db" ] && { echo "stage:"; counts "$STAGE/70online.db"; } || true
    ;;
  *) echo "usage: $0 stage|switch|rollback|status"; exit 2 ;;
esac
