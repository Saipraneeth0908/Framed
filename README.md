# Framed Obsessions

A framed-poster storefront plus an operations admin panel, on one Postgres
cluster. Four processes, four database roles, one repository.

| Process | Hostname | DB role | What it is |
|---|---|---|---|
| `web` | framedobsessions.com | `store_app` | The customer storefront |
| `admin` | admin.framedobsessions.com | `admin_app` | Staff-only operations panel |
| `collector` | e.framedobsessions.com | `ingest` | Write-only analytics beacon endpoint |
| `worker` | no ingress | `etl` | Event loader, outbox relay, scheduled jobs, metrics |

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

# Generate local secrets into deploy/.env (gitignored)
python - <<'PY'
import secrets, pathlib
from base64 import urlsafe_b64encode
keys = {
    "WEB_SECRET_KEY": secrets.token_urlsafe(48),
    "ADMIN_SECRET_KEY": secrets.token_urlsafe(48),
    "EVENT_SALT_SEED": secrets.token_urlsafe(32),
    "ADMIN_TOTP_KEY": urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "METABASE_EMBED_SECRET": secrets.token_hex(32),
}
pathlib.Path("deploy/.env").write_text("\n".join(f"{k}={v}" for k, v in keys.items()) + "\n")
PY

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
pytest                                   # 104 tests
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
  but have not been exercised against live Stripe credentials.
- Metabase dashboards are defined as marts and embed slots; the dashboards
  themselves must be built once in Metabase and their ids set via
  `FO_DASHBOARD_*`.
- Prometheus, Alertmanager, Grafana and Loki are configured but were not brought
  up in this environment; the metrics they scrape are live and verifiable.
- Most poster images are still missing. The storefront has visual fallbacks.
