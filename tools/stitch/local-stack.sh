#!/usr/bin/env bash
# Start an isolated local stack (backend + built frontend) for visual QA against Stitch.
#   tools/stitch/local-stack.sh <port-base>      e.g. 4100 -> backend :4100, frontend :4101
# Uses a COPY of the seeded test DB (/tmp/e2e-template.db, synthetic data labeled provenance='test').
# Frontend must be built first:  (cd frontend && NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/tmp/fontmock.js npx next build)
# Stop:  kill $(cat /tmp/stack-<port-base>/pids)
set -euo pipefail
B=${1:?port base}; F=$((B+1)); ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
D=/tmp/stack-$B; mkdir -p "$D"; cp /tmp/e2e-template.db "$D/e2e.db"
export APP_ENV=test SECRET_KEY=e2e-secret-0123456789abcdef0123456789abcdef DATABASE_URL=sqlite:///$D/e2e.db \
  PAYMENT_PROVIDER=mock CREDIT_PROVIDER=mock TEST_SALES_OVERRIDE=1 COMMERCE_TEST_MODE=1 \
  CORS_ORIGINS=http://127.0.0.1:$F PUBLIC_BASE_URL=http://127.0.0.1:$F PORT=$B SEED_ON_START=0
cd "$ROOT/backend"; nohup setsid /tmp/venv60/bin/python -m app.main </dev/null >"$D/backend.log" 2>&1 & echo $! > "$D/pids"
cd "$ROOT/frontend"; BACKEND_INTERNAL_URL=http://127.0.0.1:$B nohup setsid npx next start -p $F </dev/null >"$D/frontend.log" 2>&1 & echo $! >> "$D/pids"
for _ in $(seq 1 40); do curl -fs "http://127.0.0.1:$F/" >/dev/null 2>&1 && break; sleep 2; done
echo "backend :$B  frontend http://127.0.0.1:$F  (logs in $D)"
echo "logins (test only): admin — see backend/scripts/seed.py output; org employee alice@parsco.ir / Alice!23456"
