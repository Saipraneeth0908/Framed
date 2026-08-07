# Runbook

## SLOs

| Thing | Target |
|---|---|
| Storefront availability | 99.5% monthly |
| Checkout p95 | < 500ms |
| Event ingestion lag p99 | < 60s |
| Mart freshness | < 15 min (realtime models < 2 min) |
| Nightly pipeline | complete by 06:00 local |

## Alerts and what to do

### `LedgerDrift` — page

Stock numbers are wrong until this is zero.

```sql
select * from ops.ledger_drift();
```

The ledger is the truth. Correct the cache from it, never the other way around:

```sql
update ops.components c
   set on_hand  = l.d, reserved = l.r
  from (select component_id, sum(delta) d, sum(reserved_delta) r
          from ops.inventory_ledger group by component_id) l
 where l.component_id = c.id;
```

Then find how it drifted — a direct `UPDATE ops.components` outside the ledger
is the only way it can happen, and `ops.audit_log` will name the actor.

### `StripeWebhookFailures` — page

Orders may be paid at Stripe but `unpaid` here. Stripe is the system of record
for money.

1. Stripe dashboard → Developers → Webhooks → failed deliveries.
2. Replay them. `mark_paid()` is idempotent on the order, so a replay is safe.
3. Reconcile: any order with a `stripe_payment_intent` and `payment_status =
   'unpaid'` needs a manual `mark_paid`.

### `StorefrontErrorRate` / `CheckoutDown` — page

`/readyz` reports whether Postgres is reachable and whether the catalog is being
served from the JSON fallback. If it says `"catalog": "fallback"`, the storefront
is still selling from a stale catalog — that is working as designed, but carts
and orders are down, so treat it as an outage.

### `EventStreamLag` / `EventLoaderStalled` — notify

Analytics only. Never page. The Redis Stream is capped at 500k entries and the
worker's consumer group replays anything unacked, so a restart loses nothing.

```
docker compose logs -f worker
redis-cli -p 6380 XINFO GROUPS fo:events
```

### `LowStock` / `OrdersStuck` / `OrdersBlocked` — digest

These are the admin panel's action board in email form. Nothing to do at 3am.

### `MartFreshness` — notify

Every Insights tab is now showing numbers older than the SLO, without looking
any different. Check the scheduler first:

```
docker compose logs --tail 50 dbt
```

The metric comes from `meta.dbt_runs`, so an empty or stale table there and a
stale gauge are the same fact:

```sql
select model, status, run_at from meta.dbt_runs order by run_at desc limit 20;
```

A failed model leaves the previous table in place — the marts go stale rather
than empty, which is why this alert exists at all. Rebuild by hand with
`python -m scripts.run_dbt --full` once the cause is fixed.

## Analytics refresh

The `dbt` service in `deploy/docker-compose.yml` runs
`python -m scripts.run_dbt --schedule` and never exits. It builds everything
once at boot, then on the schedule in `scripts/run_dbt.py`:

| Every | Models | Feeds |
|---|---|---|
| 60s | `tag:realtime` | sessions, funnel, daily KPIs, abandoned interest |
| 1h | `tag:hourly` | page/click engagement, product journey, seller ranking, demand |
| 24h | `--full-refresh` | everything, plus all 59 data tests |

It is a plain service, not a profile: turn it off and the Insights tabs freeze
at the last build while still rendering as though they were current. Each run
is recorded in `meta.dbt_runs`, which is where `fo_mart_last_build_timestamp`
and `MartFreshness` get their numbers.

Intervals are measured from the *end* of the previous run, so a build that
overruns delays the next one instead of stacking up behind it.

## Metabase

Optional. Every Insights tab except this one is first-party and works without
it; Metabase adds a question builder for things nobody wrote a page for.

1. `docker compose --profile bi up -d metabase`, then finish setup at
   `http://localhost:3000`.
2. Add this database as **`bi_reader`** — never `postgres`, never `admin_app`.
   That role is read-only and granted `mart` and nothing else, so a runaway
   question cannot lock checkout or read customer PII.
3. Settings → Embedding → enable **static embedding**. Paste the secret it
   shows into `METABASE_EMBED_SECRET`, and set `METABASE_SITE_URL` to the
   browser-reachable URL. Both must be set or the admin page renders setup
   instructions instead of empty iframes.
4. Build the six dashboards named in `admin/embeds.py` from the `mart` tables.
5. Publish each one for embedding (dashboard → sharing → **Embed in your
   application** → Publish). An unpublished dashboard renders as a blank frame.
6. Set `FO_DASHBOARD_<KEY>` to each dashboard's id — the number in its URL. The
   defaults (1–6) assume a fresh Metabase where these were created first, which
   is a guess about your install. The id and the variable that overrides it are
   printed under every frame on the page.

The embed tokens are HS256-signed by the admin app with a 10-minute expiry, and
the admin app decides which dashboard ids it will mint tokens for — so RBAC
stays in Flask and the owner has one login, not two. Interactive embedding and
row-level sandboxing are paid Metabase tiers; neither is needed for one tenant.

## Routine operations

**Migrations.** `docker compose --profile tools run --rm dbmate up`. Every
migration has a tested `down`; `sh scripts/roundtrip.sh` proves the whole stack
rolls back and forward.

**Rotating role passwords.** The migration seeds development passwords. In
production, immediately:

```sql
alter role store_app password '...';
alter role admin_app password '...';
alter role ingest    password '...';
alter role etl       password '...';
alter role bi_reader password '...';
```

**Resetting one person's two-factor.** Lost phone, replaced phone, or an
authenticator that stopped matching. Staff screen → **Reset 2FA**, which needs
`user.manage`, is audited, and signs that account out. They keep their password
and enrol a new authenticator at their next sign-in.

If *every* owner is locked out there is no session left to press that button
from, so do it from a shell:

```powershell
python -m scripts.create_admin_user --email you@example.com --reset-totp
```

**Rotating `ADMIN_TOTP_KEY`.** TOTP secrets are Fernet-encrypted with it. There
is no re-encryption path: rotating the key orphans every stored secret at once,
and because nobody can then complete a sign-in, nobody can reach the Staff
screen to fix it. The login shows a 500 naming the recovery command. Prefer
restoring the old key; otherwise clear every enrolment and have everyone
re-enrol:

```sql
update ops.users set totp_enabled = false, totp_secret_enc = null;
```

> Do not regenerate `deploy/.env` wholesale. `python -m scripts.gen_secrets`
> only adds missing keys for this reason — overwriting `ADMIN_TOTP_KEY` breaks
> every enrolment and overwriting `ADMIN_SECRET_KEY` invalidates every session,
> which together look like "it logged me out and my two-factor is broken" with
> nothing in the logs pointing at the file.

**Locking someone out immediately.**

```sql
update ops.users set archived_at = now(), session_version = session_version + 1
 where email = '...';
```

The bump refuses every live session on its next request; the archive stops new
sign-ins.

**Backups.** Managed PITR plus a nightly `pg_dump` to object storage with a
different provider. Restore it and time it — an untested backup is a rumour.

## What is deliberately not automated

- **Refunds do not call Stripe.** `store.refunds` records the decision and the
  restock; issuing the money back is a deliberate second action in the Stripe
  dashboard. One-click refunds against live money, on a panel with four roles,
  is not a first-release feature.
- **Order cancellation does not un-consume printed stock.** Restock reverses
  whatever the ledger shows for that line — a reservation if it was still
  reserved, the physical units if it had been consumed. Paper that has already
  gone through a printer is not recoverable, and the correction is a manual
  `damage` movement.
