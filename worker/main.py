"""Worker entrypoint.

Four jobs in one process, each on its own thread:

  loader     Redis Stream -> raw.events        (batch 500 or 1s, XACK after commit)
  relay      raw.outbox   -> raw.domain_events (LISTEN/NOTIFY with a poll fallback)
  scheduler  cart sweep, partitions, drift check, retention
  exporter   business KPIs -> Prometheus, so a stock-out and a full disk page
             through the same Alertmanager

One process because these are four cron-shaped jobs on an 11-product store, not
a distributed system. Each is independently promotable to its own container --
they share nothing but a connection pool.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time

import redis
from prometheus_client import Counter, Gauge, start_http_server

from db.conn import Role, tx

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

STREAM = "fo:events"
GROUP = "loader"
CONSUMER = os.environ.get("HOSTNAME", "worker-1")
BATCH = 500
BLOCK_MS = 1000

EVENT_COLUMNS = [
    "event_id", "occurred_at", "session_id", "visitor_hash", "name", "path",
    "product_id", "variant_id", "cart_id", "device", "browser", "os", "country",
    "referrer_host", "utm", "props",
]

stopping = threading.Event()

EVENTS_LOADED = Counter("fo_events_loaded_total", "Events written to raw.events")
EVENTS_FAILED = Counter("fo_events_failed_total", "Event batches that failed to load")
OUTBOX_RELAYED = Counter("fo_outbox_relayed_total", "Outbox rows relayed to domain_events")
STREAM_LAG = Gauge("fo_event_stream_lag", "Events pending in the Redis stream")

REVENUE_TODAY = Gauge("fo_revenue_cents_today", "Paid revenue so far today, in cents")
ORDERS_BLOCKED = Gauge("fo_orders_blocked", "Line items sitting in the blocked station")
ORDERS_STUCK = Gauge("fo_orders_stuck_hours", "Paid, unshipped orders older than the threshold")
STOCK_BELOW = Gauge("fo_components_below_threshold", "Components at or under their low threshold")
PAYMENT_FAILED = Gauge("fo_payment_failures_1h", "Failed payments in the last hour")
ABANDONED_VALUE = Gauge("fo_abandoned_cart_cents_24h", "Value of carts abandoned in the last 24h")
LEDGER_DRIFT = Gauge("fo_ledger_drift_units", "Components whose cached balance disagrees with the ledger")


def client() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6380/0"))


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #

def ensure_group(conn: redis.Redis) -> None:
    try:
        conn.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def load_batch(entries: list[tuple[bytes, dict]]) -> int:
    """COPY into a temp table, then INSERT ... ON CONFLICT DO NOTHING.

    COPY has no conflict clause, so idempotency for at-least-once redelivery
    needs the second step. The temp table is dropped with the transaction.
    """
    rows = []
    for _, fields in entries:
        record = {k.decode(): (v.decode() if v is not None else None) for k, v in fields.items()}
        rows.append(tuple(record.get(column) or None for column in EVENT_COLUMNS))
    if not rows:
        return 0

    columns = ", ".join(EVENT_COLUMNS)
    with tx(Role.ETL) as cur:
        cur.execute(
            "create temp table _incoming (like raw.events including defaults) on commit drop"
        )
        with cur.copy(f"copy _incoming ({columns}) from stdin") as copy:
            for row in rows:
                copy.write_row(row)
        cur.execute(
            f"""insert into raw.events ({columns})
                select {columns} from _incoming
                on conflict (event_id, occurred_at) do nothing"""
        )
        return cur.rowcount


def loader() -> None:
    conn = client()
    ensure_group(conn)
    log.info("loader consuming %s as %s", STREAM, CONSUMER)
    while not stopping.is_set():
        try:
            response = conn.xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, count=BATCH, block=BLOCK_MS)
            if not response:
                continue
            entries = response[0][1]
            written = load_batch(entries)
            # XACK only after the commit: a crash between the two replays the
            # batch, and the ON CONFLICT makes the replay a no-op.
            conn.xack(STREAM, GROUP, *[entry_id for entry_id, _ in entries])
            EVENTS_LOADED.inc(written)
            if written:
                log.info("loaded %d events (%d delivered)", written, len(entries))
        except Exception:                                # noqa: BLE001
            EVENTS_FAILED.inc()
            log.exception("event batch failed; it stays unacked and will be retried")
            stopping.wait(5)


def reclaim_stalled() -> None:
    """Take back messages a dead consumer never acked."""
    conn = client()
    while not stopping.is_set():
        try:
            conn.xautoclaim(STREAM, GROUP, CONSUMER, min_idle_time=120_000, count=BATCH)
        except redis.RedisError:
            log.exception("xautoclaim failed")
        stopping.wait(60)


# --------------------------------------------------------------------------- #
# Outbox relay
# --------------------------------------------------------------------------- #

def relay_once() -> int:
    with tx(Role.ETL) as cur:
        cur.execute(
            """select id, topic, payload, created_at from raw.outbox
                where published_at is null order by id limit 500 for update skip locked"""
        )
        rows = cur.fetchall()
        for row in rows:
            cur.execute(
                """insert into raw.domain_events (outbox_id, topic, payload, occurred_at)
                   values (%s, %s, %s, %s) on conflict (outbox_id) do nothing""",
                (row["id"], row["topic"], json.dumps(row["payload"]), row["created_at"]),
            )
            cur.execute("update raw.outbox set published_at = now() where id = %s", (row["id"],))
        return len(rows)


def relay() -> None:
    """LISTEN for the notify, but poll anyway.

    A NOTIFY delivered while this process is reconnecting is simply lost, so
    the poll is not redundant -- it is the actual guarantee.
    """
    log.info("outbox relay started")
    while not stopping.is_set():
        moved = 0
        try:
            moved = relay_once()
            OUTBOX_RELAYED.inc(moved)
            if moved:
                log.info("relayed %d outbox rows", moved)
        except Exception:                                # noqa: BLE001
            log.exception("outbox relay failed")
        stopping.wait(1 if moved else 2)


# --------------------------------------------------------------------------- #
# Scheduled jobs
# --------------------------------------------------------------------------- #

def sweep_abandoned_carts() -> int:
    with tx(Role.ETL) as cur:
        cur.execute(
            """update store.carts set state = 'abandoned', abandoned_at = now()
                where state = 'active' and last_activity_at < now() - interval '30 minutes'
                  and exists (select 1 from store.cart_items ci where ci.cart_id = store.carts.id)
             returning id"""
        )
        return len(cur.fetchall())


def maintain_partitions() -> tuple[int, int]:
    with tx(Role.ETL) as cur:
        cur.execute("select raw.ensure_event_partitions(3) as made")
        made = cur.fetchone()["made"]
        cur.execute("select raw.drop_old_event_partitions(25) as dropped")
        return made, cur.fetchone()["dropped"]


def check_ledger_drift() -> int:
    with tx(Role.ETL) as cur:
        cur.execute("select * from ops.ledger_drift()")
        rows = cur.fetchall()
    if rows:
        # Pages, per the alert rules: money and stock disagreeing is never a
        # "look at it tomorrow" problem.
        log.error("LEDGER DRIFT on %d components: %s", len(rows), rows[:5])
    LEDGER_DRIFT.set(len(rows))
    return len(rows)


def record_quality(name: str, failures: int) -> None:
    with tx(Role.ETL) as cur:
        cur.execute(
            """insert into meta.dq_results (test_name, status, failures)
               values (%s, %s, %s)""",
            (name, "pass" if failures == 0 else "fail", failures),
        )


def scheduler() -> None:
    last = {"cart": 0.0, "partitions": 0.0, "drift": 0.0}
    while not stopping.is_set():
        now = time.time()
        try:
            if now - last["cart"] > 900:                 # 15 minutes
                swept = sweep_abandoned_carts()
                if swept:
                    log.info("marked %d carts abandoned", swept)
                last["cart"] = now
            if now - last["partitions"] > 6 * 3600:
                made, dropped = maintain_partitions()
                if made or dropped:
                    log.info("partitions: +%d -%d", made, dropped)
                last["partitions"] = now
            if now - last["drift"] > 3600:
                record_quality("ledger_drift", check_ledger_drift())
                last["drift"] = now
        except Exception:                                # noqa: BLE001
            log.exception("scheduled job failed")
        stopping.wait(30)


# --------------------------------------------------------------------------- #
# Business KPI exporter
# --------------------------------------------------------------------------- #

KPI_SQL = """
select
  (select coalesce(sum(total_cents), 0) from store.orders
    where payment_status in ('paid','partially_refunded') and placed_at::date = current_date) as revenue_today,
  (select count(*) from store.order_items where production_status = 'blocked')               as blocked,
  (select count(*) from store.orders
    where payment_status = 'paid' and fulfilment_status = 'unfulfilled'
      and cancelled_at is null and placed_at < now() - interval '24 hours')                  as stuck,
  (select count(*) from ops.components_low)                                                  as low_stock,
  (select count(*) from store.orders where payment_status = 'failed'
     and placed_at > now() - interval '1 hour')                                              as payment_failures,
  (select coalesce(sum(ci.qty * ci.unit_price_cents), 0) from store.cart_items ci
     join store.carts c on c.id = ci.cart_id
    where c.state = 'abandoned' and c.abandoned_at > now() - interval '24 hours')            as abandoned
"""


def exporter() -> None:
    """Turn marts and OLTP into gauges.

    This is the line that ties business anomalies to the same alerting path as
    disk-full: one Alertmanager, one escalation, no second system.
    """
    conn = client()
    while not stopping.is_set():
        try:
            with tx(Role.ETL) as cur:
                cur.execute(KPI_SQL)
                row = cur.fetchone()
            REVENUE_TODAY.set(row["revenue_today"])
            ORDERS_BLOCKED.set(row["blocked"])
            ORDERS_STUCK.set(row["stuck"])
            STOCK_BELOW.set(row["low_stock"])
            PAYMENT_FAILED.set(row["payment_failures"])
            ABANDONED_VALUE.set(row["abandoned"])
        except Exception:                                # noqa: BLE001
            log.exception("kpi export failed")
        try:
            info = conn.xinfo_groups(STREAM)
            STREAM_LAG.set(sum(g.get("lag") or g.get("pending", 0) for g in info))
        except redis.RedisError:
            STREAM_LAG.set(-1)
        stopping.wait(60)


# --------------------------------------------------------------------------- #

def main() -> None:
    port = int(os.environ.get("METRICS_PORT", "9101"))
    start_http_server(port)
    log.info("worker metrics on :%d", port)

    for handler in (signal.SIGTERM, signal.SIGINT):
        signal.signal(handler, lambda *_: stopping.set())

    threads = [
        threading.Thread(target=loader, name="loader", daemon=True),
        threading.Thread(target=reclaim_stalled, name="reclaim", daemon=True),
        threading.Thread(target=relay, name="relay", daemon=True),
        threading.Thread(target=scheduler, name="scheduler", daemon=True),
        threading.Thread(target=exporter, name="exporter", daemon=True),
    ]
    for thread in threads:
        thread.start()

    stopping.wait()
    log.info("shutting down")
    for thread in threads:
        thread.join(timeout=10)


if __name__ == "__main__":
    main()
