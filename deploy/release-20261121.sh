#!/usr/bin/env bash
# Release 2026-11-21 (P0 batch 2: staff roles, admin 2FA, settlement two-person control, login lockout,
# audit gaps, request-size cap) for 60online-prod. Runs ONLY after explicit owner approval (AGENTS.md rule 11).
# Steps: tag running images for instant rollback -> stage on a COPY of the DB (3100/8100) -> checks -> switch -> checks.
#
# Migration 0083 (additive: 4 new tables + 2 nullable columns on settlement_batches) is applied by
# sqlite-upgrade.sh: first during "stage" on the DB COPY (live DB untouched), then during "switch" on the live DB,
# right after the fresh backup that "switch" takes.
#
# Before running: decide ADMIN_MFA_ENFORCE in /opt/60online/secrets/backend.env (default when unset: all).
set -euo pipefail
NEW="$(cd "$(dirname "$0")/.." && pwd)"
UP="$NEW/deploy/sqlite-upgrade.sh"
ENV_FILE=/opt/60online/secrets/backend.env
code() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$@"; }
db_has() {  # $1=db file, $2=table: prints 1 if the table exists
  python3 -c "import sqlite3,sys;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?\",(sys.argv[2],)).fetchone()[0])" "$1" "$2"
}

echo "== 0. code: $(git -C "$NEW" log --oneline -1 2>/dev/null || echo "$NEW")"
echo "   ADMIN_MFA_ENFORCE in env file: $(grep -E '^ADMIN_MFA_ENFORCE=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 || true) (empty = all)"
echo "== 1. tag running images for rollback (prev-20261121)"
docker tag sixty-backend:latest  sixty-backend:prev-20261121
docker tag sixty-frontend:latest sixty-frontend:prev-20261121

echo "== 2. stage on a DB copy (live site untouched; migration 0083 runs on the copy)"
bash "$UP" stage
FAIL=0
for p in / /pack-builder /checkout /login /admin; do
  c=$(code "http://127.0.0.1:3100$p"); printf '  stage %-16s %s\n' "$p" "$c"
  case "$p" in /|/pack-builder|/checkout|/login) [ "$c" = 200 ] || FAIL=1;; esac
done
r=$(code http://127.0.0.1:8100/api/v1/health/ready); printf '  stage %-24s %s\n' /api/v1/health/ready "$r"; [ "$r" = 200 ] || FAIL=1
# Admin endpoints must refuse anonymous callers; the MFA endpoint must exist (401 without a token, not 404).
a=$(code http://127.0.0.1:8100/api/v1/admin/staff); printf '  stage %-24s %s (expect 401)\n' /api/v1/admin/staff "$a"; [ "$a" = 401 ] || FAIL=1
m=$(code http://127.0.0.1:8100/api/v1/auth/mfa/status); printf '  stage %-24s %s (expect 401)\n' /api/v1/auth/mfa/status "$m"; [ "$m" = 401 ] || FAIL=1
for t in staff_role_assignments admin_mfa admin_mfa_recovery_codes login_lockouts; do
  h=$(db_has /srv/60online-stage/data/60online.db "$t"); printf '  stage table %-26s %s\n' "$t" "$h"; [ "$h" = 1 ] || FAIL=1
done
[ "$FAIL" = 0 ] || { echo "!! stage check failed — live site NOT changed. Send this output."; exit 1; }

echo "== 3. switch to live (fresh backup first, then migration 0083 on the live DB)"
bash "$UP" switch
sleep 5
for p in / /pack-builder /checkout /login /api/v1/health/ready; do
  printf '  live  %-22s %s\n' "$p" "$(code -H 'Host: 60online.ir' "http://127.0.0.1$p")"
done
printf '  live  %-22s %s (expect 401)\n' /api/v1/admin/staff "$(code -H 'Host: 60online.ir' http://127.0.0.1/api/v1/admin/staff)"
cat <<'TXT'
== done. Next: sign in at https://60online.ir/admin with an admin account -> enrollment screen appears
   (authenticator app + recovery codes). Do this right away for every admin account.

Rollback if needed (no DB restore required: 0083 only adds tables/nullable columns; the previous code
ignores them, and /health/ready only fails when the schema is BEHIND the code):
  docker tag sixty-backend:prev-20261121 sixty-backend:latest
  docker tag sixty-frontend:prev-20261121 sixty-frontend:latest
  docker compose -f <directory of the previous release>/deploy/.compose-sixty.yml up -d
Full DB restore (only if data is damaged): bash deploy/sqlite-upgrade.sh rollback (restores the pre-switch backup).
TXT
