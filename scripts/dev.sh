#!/usr/bin/env sh
# Run storefront + admin locally against the compose Postgres/Redis.
#   sh scripts/dev.sh web     -> http://localhost:8000
#   sh scripts/dev.sh admin   -> http://localhost:8001
# Reads deploy/.env for secrets; falls back to the compose defaults for URLs.
set -e
cd "$(dirname "$0")/.."

if [ -f deploy/.env ]; then
  set -a
  . ./deploy/.env
  set +a
fi

HOST_PG="postgres://%s@localhost:5433/framedobsessions?sslmode=disable"
export DATABASE_URL="${DATABASE_URL:-$(printf "$HOST_PG" 'postgres:postgres')}"
export STORE_DATABASE_URL="${STORE_DATABASE_URL:-$(printf "$HOST_PG" 'store_app:store_app_dev')}"
export ADMIN_DATABASE_URL="${ADMIN_DATABASE_URL:-$(printf "$HOST_PG" 'admin_app:admin_app_dev')}"
export INGEST_DATABASE_URL="${INGEST_DATABASE_URL:-$(printf "$HOST_PG" 'ingest:ingest_dev')}"
export ETL_DATABASE_URL="${ETL_DATABASE_URL:-$(printf "$HOST_PG" 'etl:etl_dev')}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6380/0}"
export FLASK_SECRET_KEY="${WEB_SECRET_KEY:?set WEB_SECRET_KEY in deploy/.env}"
# Local development speaks http, so Secure cookies would never be sent back.
export FO_INSECURE_COOKIES=1

case "${1:-web}" in
  web)   exec .venv/Scripts/python.exe -m flask --app web.app run --port "${PORT:-8000}" ;;
  admin) exec .venv/Scripts/python.exe -m flask --app admin.app run --port "${PORT:-8001}" ;;
  *) echo "usage: dev.sh [web|admin]" >&2; exit 2 ;;
esac
