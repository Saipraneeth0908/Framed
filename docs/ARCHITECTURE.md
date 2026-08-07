# Architecture

One Postgres 16 cluster, medallion-layered by schema. Four stateless processes,
each holding exactly one database role. Separation of concerns is enforced by
grants, not by folder layout.

```
        ┌──────────── one Postgres 16 cluster ────────────┐
writes →│ store (OLTP) ─┐                                 │
        │ ops   (OLTP) ─┤                                 │
        │ raw   (landing, partitioned) ─┐                 │
        │                               ├→ stg → mart ────┼→ BI (bi_reader)
        │ meta  (lineage/quality) ──────┘                 │
        └─────────────────────────────────────────────────┘
                     ↓ streaming replication (Tier 2)
             read replica → analytics and BI move here
```

## Why one engine

At this scale a second engine is operational cost with no return: one backup
story, one auth model, one SQL dialect shared by the apps, dbt and Metabase.
When analytics queries start disturbing checkout latency, a read replica and a
new connection string for `bi_reader` is the whole migration.

| Contract | Now | Upgrade | Trigger |
|---|---|---|---|
| OLTP | Postgres 16, managed | + read replica | p95 checkout > 300ms, or BI slows writes |
| Warehouse | `mart` in the same cluster | replica-hosted marts | mart refresh > 5 min |
| Event buffer | Redis Stream | Redis with persistence → Redpanda | events > 50/s sustained |
| Orchestration | `scripts/run_dbt.py --schedule`, one container | Dagster | DAG exceeds ~25 models |
| Logs | Loki | ELK | full-text search over hundreds of GB |

Every upgrade is a swap behind an unchanged contract. Nothing above requires a
rewrite of application code.

## Schemas and roles

| Schema | Contents | Who can reach it |
|---|---|---|
| `store` | catalog, carts, orders, customers | `store_app` (scoped), `admin_app`, `etl` (read) |
| `ops` | users, audit, settings, components, inventory | `admin_app`, `etl` (read) — **never** `store_app` |
| `raw` | events (partitioned), outbox, Stripe | `ingest`, `etl`, `store_app` (outbox insert only) |
| `stg` / `mart` | dbt models | `etl` writes; `bi_reader` reads `mart` only |
| `meta` | pipeline runs, watermarks, quality results | `etl`, `admin_app` (read) |

A SQL-injection hole in the storefront cannot read `ops.users`,
`ops.audit_log`, or any customer PII beyond the active cart. That claim is
tested, not asserted: see `tests/test_admin_rbac.py::test_storefront_role_cannot_read_admin_tables`.

The storefront's only cross-boundary write is `raw.outbox`, in its own
transaction, and a column-level grant on three payment columns of `store.orders`
so the Stripe webhook can settle an order without being able to touch totals,
addresses or fulfilment.

## Conventions

| Concern | Decision | Why |
|---|---|---|
| Internal key | `bigint generated always as identity` | compact, no UUID bloat in foreign keys |
| External id | `public_id uuid` | never leak sequential ids in URLs or events |
| Human id | `order_no` → `FO-2026-000042` | support conversations need a speakable number |
| Money | `bigint` cents + `currency` | floats drift; the old float `base_price` was the bug |
| Time | `timestamptz`, UTC | naive timestamps are the number-one analytics bug |
| State | Postgres enums | invalid state unrepresentable; `ALTER TYPE ADD VALUE` is online |
| Delete | `archived_at` + partial unique indexes | hard-deleting financial rows is never correct |
| Mutation | generic audit trigger | unbypassable; no application path can skip it |

## The three invariants worth knowing

**Overselling is a database error.** `ops.components` carries
`check (on_hand >= 0 and reserved >= 0 and reserved <= on_hand)`. Reserving more
than exists raises, and checkout turns that into "this just sold out" rather
than a negative stock figure nobody notices for a week.

**The ledger is the truth; the balance is a cache.** `ops.inventory_ledger` is
append-only (a trigger refuses `UPDATE`/`DELETE`; corrections are new rows).
`ops.ledger_drift()` asserts `sum(delta) = on_hand` per component; the worker
checks hourly and it pages.

**History freezes when money moves.** Once an order leaves `unpaid`, a trigger
refuses changes to any financial column on `order_items` — quantity, price,
snapshot, cost. Production status stays editable, because the workshop board
still has to work. Corrections happen through refunds.

## Data flow

```
  CUSTOMER SITE (store_app)
  ├─ track.js ──sendBeacon──→ collector ──XADD──→ Redis Stream
  │                            (validate · drop bots · hash visitor          │
  │                             country from CF-IPCountry · discard the IP)  │
  │                                                                          │
  └─ order writes ──→ store.* + raw.outbox   (ONE transaction)               │
                              │                                             │
                        relay (LISTEN/NOTIFY + poll)                        │
                              ↓                          worker: COPY → raw.events
                      raw.domain_events                              │
                              └──────────┬──────────────────────────┘
                                    dbt: stg → mart
                                         │
                ┌────────────────────────┼────────────────────────┐
                ↓                        ↓                        ↓
        Flask admin (admin_app)   Metabase (bi_reader)    KPI exporter
        operational, writes       analytics, read-only    → Prometheus
```

Coupling, stated explicitly:

- The storefront knows exactly one analytics fact: an HTTP endpoint URL. No
  shared library, no import, no schema dependency. Collector down → beacons fail
  silently and the storefront does not notice.
- The admin never calls the storefront and the storefront never calls the admin.
  They read the same database through different roles. Zero HTTP coupling.
- Storefront deploys do not touch analytics; analytics deploys do not touch the
  storefront.

## Privacy

The raw IP exists only inside a collector request. It produces a country and a
salted visitor hash, then is discarded — never persisted, never logged. The salt
is generated randomly per UTC day and held in Redis with a 36-hour TTL, so
yesterday's visitors are cryptographically unlinkable rather than merely
obscured. No analytics cookie is set, so no consent banner is legally required;
the cart cookie is strictly necessary.

Customer PII lives in `store` and `ops` and never enters `raw.events` or any
mart. `dbt/tests/assert_no_pii_in_marts.sql` fails the build if a future model
selects an email or a name into a schema Metabase can read.

## Deliberate deviations from the original plan

1. **Enum types live in `public`.** They are shared by `store` and `ops`; app
   roles get `USAGE` (never `CREATE`) so explicit casts resolve.
2. **`variant_combo` is a unique index, not a table constraint.** Postgres does
   not allow an expression (`coalesce(finish,'')`) in a table-level `UNIQUE`.
3. **The ledger carries `reserved_delta` alongside `delta`.** Reservations must
   not change `on_hand`, or `sum(delta) = on_hand` stops holding. Two columns
   keep both balances provable from the same append-only table.
4. **Production timings come from `ops.audit_log`.** The audit trigger already
   records every `production_status` change with a before and after; a dedicated
   events table would be a second source of truth for the same fact.
5. **Funnel steps are cumulative in `int_funnel_steps`.** Read literally off the
   events, a session that adds to cart from a listing card reports a purchase
   with no checkout. The monotonicity test then catches sessionization bugs
   instead of restating what the browser happened to send.
6. **Partitions are maintained by two SQL functions, not pg_partman.** The
   extension is not in `postgres:16-alpine` and this is twenty lines.
7. **`ingest` exists but does not write today.** The collector buffers to Redis
   and never opens a Postgres connection; the loader (`etl`) writes. The grant
   stays so a direct-write collector is a config change, not a migration.
