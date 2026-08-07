"""Sprint 4 acceptance: events survive the whole path, and replaying anything
changes nothing.

The collector, the Redis Stream and the loader are exercised for real. Only the
process boundary is collapsed -- the code under test is the code that runs in
production.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from db.conn import Role, tx


@pytest.fixture()
def collector():
    from collector.app import app

    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def drain_stream():
    """Each test owns the stream, so a leftover event cannot skew a count."""
    from collector.app import STREAM, client

    client().delete(STREAM)
    yield
    client().delete(STREAM)


def an_event(name: str, session_id: str, **props) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "occurred_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        "name": name,
        "path": "/shop",
        "props": props,
    }


def stream_entries():
    from collector.app import STREAM, client

    return client().xrange(STREAM)


# --------------------------------------------------------------------------- #
# Collector
# --------------------------------------------------------------------------- #

def test_a_beacon_is_accepted_and_buffered(collector):
    sid = str(uuid.uuid4())
    response = collector.post("/e", json=[an_event("page_view", sid), an_event("product_view", sid)])
    assert response.status_code == 204
    assert len(stream_entries()) == 2


def test_the_collector_never_returns_an_error_to_a_beacon(collector):
    """sendBeacon cannot retry, so a 4xx is a dropped event and a console error."""
    assert collector.post("/e", data="not json").status_code == 204
    assert collector.post("/e", json={"name": "not_a_real_event"}).status_code == 204
    assert collector.post("/e", json={"name": "page_view"}).status_code == 204  # no ids
    assert stream_entries() == []


def test_unknown_event_names_are_dropped_not_stored(collector):
    sid = str(uuid.uuid4())
    collector.post("/e", json=[an_event("page_view", sid), {**an_event("page_view", sid), "name": "evil"}])
    assert len(stream_entries()) == 1


def test_crawlers_are_dropped(collector):
    response = collector.post(
        "/e", json=an_event("page_view", str(uuid.uuid4())),
        headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
    )
    assert response.status_code == 204
    assert stream_entries() == []


def test_the_raw_ip_is_never_stored(collector):
    sid = str(uuid.uuid4())
    collector.post("/e", json=an_event("page_view", sid),
                   environ_overrides={"REMOTE_ADDR": "203.0.113.42"})
    stored = stream_entries()[0][1]
    blob = b" ".join(stored.keys()) + b" " + b" ".join(v for v in stored.values() if v)
    assert b"203.0.113.42" not in blob
    assert stored[b"visitor_hash"] and len(stored[b"visitor_hash"]) == 64


def test_the_same_visitor_hashes_consistently_within_a_day(collector):
    from collector.app import visitor_hash

    assert visitor_hash("203.0.113.42", "UA/1") == visitor_hash("203.0.113.42", "UA/1")
    assert visitor_hash("203.0.113.42", "UA/1") != visitor_hash("203.0.113.43", "UA/1")


def test_a_client_clock_far_in_the_past_is_corrected(collector):
    sid = str(uuid.uuid4())
    event = an_event("page_view", sid)
    event["occurred_at"] = 1  # 1970
    collector.post("/e", json=event)
    stored = stream_entries()[0][1]
    assert stored[b"occurred_at"].decode().startswith(str(datetime.now(timezone.utc).year))


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #

def _load_everything_pending():
    from worker.main import load_batch

    entries = [(entry_id, fields) for entry_id, fields in stream_entries()]
    return load_batch(entries), entries


def test_events_reach_postgres(collector):
    sid = str(uuid.uuid4())
    collector.post("/e", json=[an_event("page_view", sid), an_event("add_to_cart", sid, slug="x")])
    written, _ = _load_everything_pending()
    assert written == 2

    with tx(Role.SUPER) as cur:
        cur.execute("select name from raw.events where session_id = %s order by name", (sid,))
        assert [r["name"] for r in cur.fetchall()] == ["add_to_cart", "page_view"]


def test_replaying_a_batch_writes_nothing_twice(collector):
    """At-least-once delivery, exactly-once storage. XACK-after-commit means a
    crash replays the batch, and this is what makes that safe."""
    sid = str(uuid.uuid4())
    collector.post("/e", json=[an_event("page_view", sid) for _ in range(3)])
    first, entries = _load_everything_pending()
    assert first == 3

    from worker.main import load_batch

    assert load_batch(entries) == 0, "a replayed batch must be a no-op"
    with tx(Role.SUPER) as cur:
        cur.execute("select count(*) as n from raw.events where session_id = %s", (sid,))
        assert cur.fetchone()["n"] == 3


def test_props_survive_as_queryable_json(collector):
    sid = str(uuid.uuid4())
    collector.post("/e", json=an_event("search_zero_results", sid, term="lambo poster", results=0))
    _load_everything_pending()
    with tx(Role.SUPER) as cur:
        cur.execute(
            "select props ->> 'term' as term from raw.events where session_id = %s", (sid,)
        )
        assert cur.fetchone()["term"] == "lambo poster"


# --------------------------------------------------------------------------- #
# Outbox relay
# --------------------------------------------------------------------------- #

def test_the_outbox_relay_is_idempotent(client):
    from worker.main import relay_once

    client.post("/cart/add", data={"slug": "mount-fuji-maple", "qty": "1", "frame": "black", "size": "A4"})
    client.post("/checkout", data={
        "name": "Relay Tester", "email": "relay@example.com", "street": "3 Kiln Road",
        "city": "Leeds", "state": "NY", "zip": "10001",
    })

    moved = relay_once()
    assert moved >= 2                     # order.placed and order.paid
    assert relay_once() == 0, "already-published rows must not be relayed again"

    with tx(Role.SUPER) as cur:
        cur.execute(
            """select count(*) as n from raw.domain_events
                where topic in ('order.placed', 'order.paid')"""
        )
        assert cur.fetchone()["n"] >= 2
        cur.execute("select count(*) as n from raw.outbox where published_at is null")
        assert cur.fetchone()["n"] == 0


def test_the_outbox_row_is_written_in_the_order_transaction(client):
    """No second write that can fail on its own: analytics can never disagree
    with the ledger."""
    with tx(Role.SUPER) as cur:
        cur.execute("select count(*) as n from raw.outbox where topic = 'order.placed'")
        before = cur.fetchone()["n"]

    client.post("/cart/add", data={"slug": "work-hard-in-silence", "qty": "1"})
    client.post("/checkout", data={
        "name": "Atomic", "email": "atomic@example.com", "street": "4 Kiln Road",
        "city": "Leeds", "state": "NY", "zip": "10001",
    })

    with tx(Role.SUPER) as cur:
        cur.execute(
            """select o.id from store.orders o
                where o.email = 'atomic@example.com' order by o.id desc limit 1"""
        )
        order_id = cur.fetchone()["id"]
        cur.execute(
            """select count(*) as n from raw.outbox
                where topic = 'order.placed' and (payload ->> 'order_id')::bigint = %s""",
            (order_id,),
        )
        assert cur.fetchone()["n"] == 1
        cur.execute("select count(*) as n from raw.outbox where topic = 'order.placed'")
        assert cur.fetchone()["n"] == before + 1


# --------------------------------------------------------------------------- #
# Scheduled jobs
# --------------------------------------------------------------------------- #

def test_partition_maintenance_is_idempotent():
    from worker.main import maintain_partitions

    maintain_partitions()
    made, dropped = maintain_partitions()
    assert made == 0, "partitions for the next three months already exist"
    assert dropped == 0


def test_abandoned_cart_sweep_only_takes_stale_carts_with_items(client):
    from worker.main import sweep_abandoned_carts

    client.post("/cart/add", data={"slug": "mclaren-w1-orange", "qty": "1"})
    with client.session_transaction() as sess:
        token = sess["cart_token"]

    assert sweep_abandoned_carts() == 0, "a cart touched seconds ago is not abandoned"

    with tx(Role.SUPER) as cur:
        cur.execute(
            "update store.carts set last_activity_at = now() - interval '2 hours' where public_id = %s",
            (token,),
        )
    assert sweep_abandoned_carts() == 1
    assert sweep_abandoned_carts() == 0, "sweeping twice must not re-mark"


def test_the_drift_check_reports_zero_on_a_healthy_ledger():
    from worker.main import check_ledger_drift

    assert check_ledger_drift() == 0


# --------------------------------------------------------------------------- #
# Mart refresh -- the schedule is deployed code now, so it is testable
# --------------------------------------------------------------------------- #

def test_the_schedule_covers_every_tag_the_models_use():
    """A tag on a model with no matching schedule entry never rebuilds."""
    from pathlib import Path

    from scripts.run_dbt import SCHEDULE

    scheduled = {arg.split(":", 1)[1] for _, extra in SCHEDULE for arg in extra if arg.startswith("tag:")}
    tagged = set()
    for model in Path("dbt/models/marts").glob("*.sql"):
        head = model.read_text(encoding="utf-8").split("\n", 1)[0]
        tagged.update(t.strip(" '\"") for t in head.partition("tags=[")[2].partition("]")[0].split(","))
    assert tagged - {""} <= scheduled, "a mart is tagged for a schedule that does not exist"


def test_each_schedule_entry_maps_to_a_real_dbt_command(monkeypatch):
    import scripts.run_dbt as runner

    seen = []
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or _completed())
    monkeypatch.setattr(runner, "record", lambda path: (0, 0))

    for _, extra in runner.SCHEDULE:
        runner.run_once(extra)

    assert seen[0] == ["dbt", "build", "--select", "tag:realtime"]
    assert seen[-1] == ["dbt", "build", "--full-refresh"]


def test_a_failed_build_does_not_kill_the_scheduler(monkeypatch):
    """Postgres bouncing must delay the next build, not end all of them."""
    import scripts.run_dbt as runner

    monkeypatch.setattr(runner, "run_once", _raise)
    runner._guarded(["--select", "tag:realtime"])         # must not propagate


def _raise(*_args, **_kwargs):
    raise RuntimeError("connection refused")


def _completed():
    import subprocess

    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
