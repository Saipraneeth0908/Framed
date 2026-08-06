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

**Rotating `ADMIN_TOTP_KEY`.** TOTP secrets are Fernet-encrypted with it. There
is no re-encryption path: rotating the key means every user re-enrols.

```sql
update ops.users set totp_enabled = false, totp_secret_enc = null;
```

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
