#!/usr/bin/env bash
# Release 2026-11-19 (mega-market homepage, PR #28) for 60online-prod.
# Owner approved deploying to the live site (pre-launch site, no real customers yet).
# Steps: tag running images for instant rollback -> stage on a COPY of the DB (3100/8100) -> check -> switch -> check.
set -euo pipefail
NEW="$(cd "$(dirname "$0")/.." && pwd)"
UP="$NEW/deploy/sqlite-upgrade.sh"
code() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$@"; }

echo "== 0. code: $(git -C "$NEW" log --oneline -1 2>/dev/null || echo "$NEW")"
echo "== 1. tag running images for rollback (prev-20261119)"
docker tag sixty-backend:latest  sixty-backend:prev-20261119
docker tag sixty-frontend:latest sixty-frontend:prev-20261119

echo "== 2. stage (live site untouched)"
bash "$UP" stage
FAIL=0
for p in / /pack-builder /benefits /organization /checkout /stores /assistant; do
  c=$(code "http://127.0.0.1:3100$p"); printf '  stage %-16s %s\n' "$p" "$c"
  case "$p" in /|/pack-builder|/checkout) [ "$c" = 200 ] || FAIL=1;; esac
done
[ "$FAIL" = 0 ] || { echo "!! stage check failed — live site NOT changed. Send this output."; exit 1; }

echo "== 3. switch to live"
bash "$UP" switch
sleep 5
for p in / /pack-builder /benefits /organization /checkout /stores /api/v1/health/ready; do
  printf '  live  %-22s %s\n' "$p" "$(code -H 'Host: 60online.ir' "http://127.0.0.1$p")"
done
cat <<'TXT'
== done. Rollback if needed (no DB restore required — this release has no migrations):
  docker tag sixty-backend:prev-20261119 sixty-backend:latest
  docker tag sixty-frontend:prev-20261119 sixty-frontend:latest
  docker compose -f /opt/60online-rel-20261118/deploy/.compose-sixty.yml up -d
TXT
