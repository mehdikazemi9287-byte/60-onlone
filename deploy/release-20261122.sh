#!/usr/bin/env bash
# Release 2026-11-22 (P1 batch 1: a separate cart per shopping mode, customer cancellation before shipment,
# address book) for 60online-prod. Runs ONLY after explicit owner approval (AGENTS.md rule 11).
# Steps: tag running images for instant rollback -> stage on a COPY of the DB (3100/8100) -> checks -> switch -> checks.
#
# Migrations 0084-0086 are applied by sqlite-upgrade.sh: first during "stage" on the DB COPY (live DB untouched),
# then during "switch" on the live DB, right after the fresh backup that "switch" takes.
#   0084: carts.shopping_mode (existing carts -> 'personal'), one active cart per (user, mode) index replaces the
#         one-per-user index, nullable shopping_mode on payment_intents and orders. No row deleted or rewritten.
#   0085: new tables order_cancellations (append-only) and order_refunds; ledger account 2060.
#   0086: addresses.updated_at (nullable) and one-default-per-user index on the existing, unused addresses table.
set -euo pipefail
NEW="$(cd "$(dirname "$0")/.." && pwd)"
UP="$NEW/deploy/sqlite-upgrade.sh"
code() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$@" || true; }  # never abort the script: a refused connection prints 000
wait_up() {  # $1=url: wait up to 90s until it answers anything but 000 (frontend needs a few seconds after "Started")
  for _ in $(seq 1 45); do [ "$(code "$1")" != 000 ] && return 0; sleep 2; done; return 0
}
db_has() {  # $1=db file, $2=table: prints 1 if the table exists
  python3 -c "import sqlite3,sys;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?\",(sys.argv[2],)).fetchone()[0])" "$1" "$2" 2>/dev/null || echo ERR
}
db_col() {  # $1=db file, $2=table, $3=column: prints 1 if the column exists
  python3 -c "import sqlite3,sys;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(int(any(r[1]==sys.argv[3] for r in c.execute('PRAGMA table_info('+sys.argv[2]+')'))))" "$1" "$2" "$3" 2>/dev/null || echo ERR
}
db_q() {  # $1=db file, $2=SQL returning one value
  python3 -c "import sqlite3,sys;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);print(c.execute(sys.argv[2]).fetchone()[0])" "$1" "$2" 2>/dev/null || echo ERR
}

echo "== 0. code: $(git -C "$NEW" log --oneline -1 2>/dev/null || echo "$NEW")"
echo "== 1. tag running images for rollback (prev-20261122)"
docker tag sixty-backend:latest  sixty-backend:prev-20261122
docker tag sixty-frontend:latest sixty-frontend:prev-20261122

echo "== 2. stage on a DB copy (live site untouched; migrations 0084-0086 run on the copy)"
bash "$UP" stage
wait_up http://127.0.0.1:3100/
FAIL=0
STAGE_DB=/srv/60online-stage/data/60online.db
for p in / /pack-builder /cart /checkout /login /me/addresses /admin; do
  c=$(code "http://127.0.0.1:3100$p"); printf '  stage %-16s %s\n' "$p" "$c"
  case "$p" in /|/pack-builder|/cart|/checkout|/login|/me/addresses) [ "$c" = 200 ] || FAIL=1;; esac
done
r=$(code http://127.0.0.1:8100/api/v1/health/ready); printf '  stage %-28s %s\n' /api/v1/health/ready "$r"; [ "$r" = 200 ] || FAIL=1
# New customer endpoints must refuse anonymous callers (401, not 404 = route exists); admin queue too.
for e in /api/v1/cart/summary /api/v1/me/addresses /api/v1/admin/order-refunds; do
  a=$(code "http://127.0.0.1:8100$e"); printf '  stage %-28s %s (expect 401)\n' "$e" "$a"; [ "$a" = 401 ] || FAIL=1
done
a=$(code -X POST http://127.0.0.1:8100/api/v1/orders/ORD-0/cancel); printf '  stage %-28s %s (expect 401)\n' "POST /orders/<n>/cancel" "$a"; [ "$a" = 401 ] || FAIL=1
# 2026-11-21 contents (migration 0083) ship in this release too when 2026-11-21 was not deployed separately.
for e in /api/v1/admin/staff /api/v1/auth/mfa/status; do
  a=$(code "http://127.0.0.1:8100$e"); printf '  stage %-28s %s (expect 401)\n' "$e" "$a"; [ "$a" = 401 ] || FAIL=1
done
for t in staff_role_assignments admin_mfa admin_mfa_recovery_codes login_lockouts order_cancellations order_refunds; do
  h=$(db_has "$STAGE_DB" "$t"); printf '  stage table %-30s %s\n' "$t" "$h"; [ "$h" = 1 ] || FAIL=1
done
for tc in carts:shopping_mode payment_intents:shopping_mode orders:shopping_mode addresses:updated_at; do
  h=$(db_col "$STAGE_DB" "${tc%%:*}" "${tc##*:}"); printf '  stage column %-29s %s\n' "$tc" "$h"; [ "$h" = 1 ] || FAIL=1
done
h=$(db_q "$STAGE_DB" "SELECT count(*) FROM sqlite_master WHERE type='index' AND name='idx_carts_one_active_mode'")
printf '  stage index %-30s %s\n' idx_carts_one_active_mode "$h"; [ "$h" = 1 ] || FAIL=1
h=$(db_q "$STAGE_DB" "SELECT count(*) FROM carts WHERE shopping_mode <> 'personal'")
printf '  stage %-36s %s (expect 0: every existing cart is personal)\n' "non-personal carts after 0084" "$h"; [ "$h" = 0 ] || FAIL=1
h=$(db_q "$STAGE_DB" "SELECT count(*) FROM ledger_accounts WHERE code='2060'")
printf '  stage %-36s %s\n' "ledger account 2060" "$h"; [ "$h" = 1 ] || FAIL=1
[ "$FAIL" = 0 ] || { echo "!! stage check failed — live site NOT changed. Send this output."; exit 1; }

echo "== 3. switch to live (fresh backup first, then migrations 0084-0086 on the live DB)"
bash "$UP" switch
wait_up http://127.0.0.1:3000/
for p in / /pack-builder /cart /checkout /login /me/addresses /api/v1/health/ready; do
  printf '  live  %-22s %s\n' "$p" "$(code -H 'Host: 60online.ir' "http://127.0.0.1$p")"
done
printf '  live  %-22s %s (expect 401)\n' /api/v1/me/addresses "$(code -H 'Host: 60online.ir' http://127.0.0.1/api/v1/me/addresses)"
cat <<'TXT'
== done. Next (owner, in a browser): switch «شخصی / پرسنل سازمان / سازمانی و عمده» on /cart and check that each
   mode shows its own cart; open an unshipped test order and check «لغو سفارش»; add an address in /me/addresses.
   Finance: refunds owed for cancelled card orders are listed at GET /api/v1/admin/order-refunds (no admin page yet).

Rollback if needed (no DB restore required: 0084-0086 only add columns/tables/indexes; the previous code ignores
them. After a rollback a user with carts in several modes sees one of them; cancelled orders stay cancelled):
  docker tag sixty-backend:prev-20261122 sixty-backend:latest
  docker tag sixty-frontend:prev-20261122 sixty-frontend:latest
  docker compose -f /opt/60online-rel-20261120/deploy/.compose-sixty.yml up -d   # code running before this release (2026-11-21 was shipped inside this release)
Full DB restore (only if data is damaged): bash deploy/sqlite-upgrade.sh rollback (restores the pre-switch backup).
TXT
