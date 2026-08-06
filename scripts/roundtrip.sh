#!/usr/bin/env sh
# Acceptance gate for Sprint 0: every migration must roll all the way down and
# back up cleanly. Run from deploy/:  sh ../scripts/roundtrip.sh
set -e

count() {
  docker compose exec -T postgres psql -U postgres -d framedobsessions -tAc \
    "select count(*) from schema_migrations" 2>/dev/null | tr -d '[:space:]' || echo 0
}

echo "applied before: $(count)"
while [ "$(count)" != "0" ]; do
  docker compose --profile tools run --rm dbmate down >/dev/null
done
echo "applied after rollback: $(count)"
docker compose --profile tools run --rm dbmate up | grep -c '^Applied' | xargs echo "re-applied:"
echo "applied now: $(count)"
