#!/bin/sh
# Migrate, optionally seed, then serve.
# Fails fast if SECRET_KEY is absent.
# SEED_ON_START is ignored in production (APP_ENV=production).
set -e

# Worker container: same image, runs background jobs + monitoring instead of the API.
# Migrations are left to the backend container (one migrator only).
if [ "${1:-}" = "worker" ]; then
  echo "→ starting scheduler"
  exec python -m scripts.scheduler
fi

echo "→ applying migrations"
python -m scripts.migrate

# Production guard: never seed demo data in production.
# In non-production environments SEED_ON_START=1 is the default.
_APP_ENV="${APP_ENV:-development}"
_SEED="${SEED_ON_START:-1}"

if [ "${_APP_ENV}" = "production" ]; then
  echo "→ production environment — skipping seed (SEED_ON_START ignored)"
elif [ "${_SEED}" = "1" ]; then
  echo "→ seeding demo data (APP_ENV=${_APP_ENV})"
  python -m scripts.seed
else
  echo "→ skipping seed (SEED_ON_START=${_SEED})"
fi

echo "→ starting API on :${PORT:-8000}"
if [ "${_APP_ENV}" = "production" ] || [ "${_APP_ENV}" = "staging" ]; then
  # One process + threads: the in-memory rate limiter and OTP counters stay exact. Scale threads, not workers,
  # until rate limiting moves to a shared store.
  exec gunicorn app.wsgi:app --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads "${GUNICORN_THREADS:-8}" \
    --timeout 60 --graceful-timeout 30 --access-logfile - --forwarded-allow-ips "*"
fi
exec python -m app.main
