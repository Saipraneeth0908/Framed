#!/usr/bin/env sh
# Acceptance gate for Sprint 0: every migration must roll all the way down and
# back up cleanly. Run from deploy/:  sh ../scripts/roundtrip.sh
set -e

count() {
  docker compose exec -T postgres psql -U postgres -d framedobsessions -tAc \
    "select count(*) from schema_migrations" 2>/dev/null | tr -d '[:space:]' || echo 0
}

echo "applied before: $(count)"

# dbt materialises views in stg/ and tables in mart/ that depend on store and
# ops tables. They are derived artifacts, not migration-managed, so they are
# dropped here rather than taught to every down migration.
# stg_% also catches the prefixed schemas dbt creates when generate_schema_name
# is not overridden -- they outlive a config fix and then block the rollback.
docker compose exec -T postgres psql -U postgres -d framedobsessions -q -c "
do \$\$
declare s text;
begin
  for s in select nspname from pg_namespace
            where nspname in ('stg', 'mart') or nspname like 'stg\\_%' or nspname like 'mart\\_%'
  loop
    execute format('drop schema if exists %I cascade', s);
  end loop;
end \$\$;" >/dev/null 2>&1 || true

while [ "$(count)" != "0" ]; do
  docker compose --profile tools run --rm dbmate down >/dev/null
done
echo "applied after rollback: $(count)"
docker compose --profile tools run --rm dbmate up | grep -c '^Applied' | xargs echo "re-applied:"
echo "applied now: $(count)"
