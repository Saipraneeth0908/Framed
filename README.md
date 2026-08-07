# Framed Obsessions

A framed-poster storefront plus an operations admin panel, on one Postgres
cluster. Five processes, four database roles, one repository.

| Process | Hostname | DB role | What it is |
|---|---|---|---|
| `web` | framedobsessions.com | `store_app` | The customer storefront |
| `admin` | admin.framedobsessions.com | `admin_app` | Staff-only operations panel |
| `collector` | e.framedobsessions.com | `ingest` | Write-only analytics beacon endpoint |
| `worker` | no ingress | `etl` | Event loader, outbox relay, scheduled jobs, metrics |
| `dbt` | no ingress | `etl` | Mart refresh on a schedule, recorded in `meta.dbt_runs` |

The admin panel is a **separate application on a separate hostname with its own
cookie and its own secret**. It shares no routes and no session with the
storefront, and the storefront's database role has no access to the `ops` schema
at all. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- Python 3.12
- Docker (Postgres 16 + Redis 7 come from `deploy/docker-compose.yml`)

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

# Postgres on 5433 and Redis on 6380 (offset so a local install does not clash)
cd deploy
docker compose up -d postgres redis

# Generate local secrets into deploy/.env (gitignored). Safe to re-run: it only
# fills in what is missing, because regenerating ADMIN_TOTP_KEY would break
# every enrolled authenticator and ADMIN_SECRET_KEY would sign everybody out.
python -m scripts.gen_secrets

# Schema, then the catalog
docker compose --profile tools run --rm dbmate up
cd .. ; python -m scripts.seed_catalog
```

Run the two apps:

```powershell
sh scripts/dev.sh web     # http://127.0.0.1:8000
sh scripts/dev.sh admin   # http://127.0.0.1:8001
```

Create the first admin account:

```powershell
python -m scripts.create_admin_user --email you@example.com --name "Your Name" --role owner
```

The password is printed once. Owner and manager accounts must set up TOTP at
first sign-in; the QR code is rendered inline.

## Checks

```powershell
ruff check .
pytest                                   # 148 tests
sh scripts/roundtrip.sh                  # every migration down and back up (run from deploy/)
cd dbt ; dbt build                       # 21 models, 59 data tests
```

`sh scripts/reset_db.sh` (from `deploy/`) rebuilds the schema and reseeds.

## Layout

```
web/         storefront routes, carts, orders, payments adapter
admin/       admin app: auth, RBAC, views, templates, stylesheet
collector/   write-only event endpoint
worker/      loader, outbox relay, scheduled jobs, KPI exporter
db/          migrations (dbmate) + connection pools + repositories
dbt/         staging -> intermediate -> marts, plus data tests
deploy/      compose, Dockerfile, Caddyfile, Prometheus, Alertmanager, Grafana
scripts/     dev runner, seeds, migration round-trip, dbt scheduler
docs/        architecture and runbook
```

## Current limitations

- Payments run through a **stub gateway** unless `STRIPE_SECRET_KEY` is set. The
  Stripe Checkout path and its webhook signature verification are implemented
  but have not been exercised against live Stripe credentials. Until they are,
  orders settle instantly and the Orders screen is not describing real money.
- Metabase needs a one-time manual setup — build the six dashboards, publish
  each for embedding, set `FO_DASHBOARD_*`. Steps in
  [docs/RUNBOOK.md](docs/RUNBOOK.md#metabase). Everything else under Insights is
  first-party and works without it.
- Most poster images are still missing. The storefront has visual fallbacks.

## Before going live

- Remove the demo analytics data: `python -m scripts.generate_demo_traffic
  --purge`. It is tagged `props.demo = true` and purges cleanly, but every
  Insights number is meaningless until it is gone.
- Rotate the seeded database role passwords (see the runbook).
- Bring up monitoring: `docker compose --profile monitoring up -d`.
