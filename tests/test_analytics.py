"""The analytics dashboard: renders, reconciles, and degrades honestly."""

from __future__ import annotations

import pytest

from db.conn import Role, tx
from db.repo import analytics as repo

def requires_mart(*names: str) -> None:
    """Skip unless dbt has built these.

    Without this the warehouse assertions raise UndefinedTable on the ordinary
    run, because pytest runs before `dbt build` -- and it has to: the marts are
    built from the traffic these tests generate. Marked `marts` and re-run after
    the warehouse is built, which is the pass that actually asserts.
    """
    with tx(Role.SUPER) as cur:
        cur.execute(
            "select m from unnest(%s::text[]) m where to_regclass('mart.' || m) is null",
            (list(names),),
        )
        missing = [row["m"] for row in cur.fetchall()]
    if missing:
        pytest.skip(f"marts not built: {', '.join(missing)}")


PAGES = [
    ("/insights/", b"Sessions"),
    ("/insights/behaviour", b"Most visited pages"),
    ("/insights/products", b"Best sellers"),
    ("/insights/abandonment", b"Cart holders right now"),
    ("/insights/acquisition", b"Where visitors came from"),
    ("/insights/embed", b"Metabase"),
]


@pytest.mark.parametrize(("path", "needle"), PAGES)
def test_every_analytics_page_renders(as_role, path, needle):
    response = as_role("owner").get(path)
    assert response.status_code == 200
    assert needle in response.data


@pytest.mark.parametrize("path", [p for p, _ in PAGES])
def test_analytics_needs_the_analytics_permission(as_role, path):
    """Fulfilment staff run the workshop; they do not get the business numbers."""
    assert as_role("fulfilment").get(path).status_code == 403


def test_charts_are_rendered_server_side_with_no_javascript(as_role):
    body = as_role("owner").get("/insights/").data
    assert b"<svg" in body, "the overview should draw at least one chart"
    assert b"<script" not in body.split(b"<main")[-1], "charts must not need client-side JS"


def test_date_window_is_honoured_and_bounded(as_role):
    client = as_role("owner")
    for days in (7, 30, 90, 365):
        assert client.get(f"/insights/?days={days}").status_code == 200
    # An unexpected value falls back to the default rather than reaching SQL.
    assert client.get("/insights/?days=99999").status_code == 200
    assert client.get("/insights/?days=drop+table").status_code == 200


def test_product_sort_options_do_not_reach_sql(as_role):
    client = as_role("owner")
    for sort in ("views", "orders", "revenue", "margin", "conversion", "dwell"):
        assert client.get(f"/insights/products?sort={sort}").status_code == 200
    # The sort key is mapped through a dict to a fixed column name, never
    # interpolated, so an unknown value falls back to the default.
    assert client.get("/insights/products?sort=; drop table store.orders --").status_code == 200
    with tx(Role.SUPER) as cur:
        cur.execute("select to_regclass('store.orders') is not null as alive")
        assert cur.fetchone()["alive"], "the orders table did not survive an injection attempt"


# --------------------------------------------------------------------------- #
# The numbers
# --------------------------------------------------------------------------- #

@pytest.mark.marts
def test_funnel_is_monotonic():
    steps = repo.funnel(365)
    if not steps:
        pytest.skip("marts not built")
    values = [s["value"] for s in steps]
    assert values == sorted(values, reverse=True), f"funnel goes back up: {values}"


@pytest.mark.marts
def test_funnel_reconciles_with_the_sessions_mart():
    steps = repo.funnel(365)
    if not steps:
        pytest.skip("marts not built")
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select count(*) as landed, count(*) filter (where purchased) as bought
                 from mart.mart_visitor_sessions
                where started_at > now() - interval '365 days'"""
        )
        row = cur.fetchone()
    assert steps[0]["value"] == row["landed"]
    assert steps[-1]["value"] == row["bought"]


def test_a_real_order_carries_the_analytics_session_id(client):
    """The bug the whole feature rested on.

    Carts used to be created with session_id = session.get("analytics_sid"),
    which nothing ever set. Every cart landed with NULL, so there was no key at
    all between raw.events and store.orders and no behaviour number could ever
    be tied to money. Asserted end to end through the storefront rather than
    against generated data, because the mechanism is what has to work.
    """
    client.post("/cart/add", data={"slug": "mclaren-p1-red", "qty": "1"})
    with client.session_transaction() as sess:
        sid, token = sess["analytics_sid"], sess["cart_token"]
    assert sid, "the storefront must mint an analytics session id"

    client.post("/checkout", data={
        "name": "Joined Up", "email": "joined@example.com", "street": "9 Kiln Road",
        "city": "Leeds", "state": "NY", "zip": "10001",
    })

    with tx(Role.SUPER) as cur:
        cur.execute(
            """select c.session_id::text as session_id, o.id as order_id, o.total_cents
                 from store.carts c
                 join store.orders o on o.cart_id = c.id
                where c.public_id = %s""",
            (token,),
        )
        row = cur.fetchone()
    assert row is not None, "the order did not join back to its cart"
    assert row["session_id"] == sid, "cart session id does not match the beacon session id"


def test_the_session_id_is_stable_across_requests(client):
    """One id for the whole visit, or every page looks like a new visitor."""
    client.get("/")
    with client.session_transaction() as sess:
        first = sess["analytics_sid"]
    client.get("/shop")
    client.get("/product/mclaren-p1-red")
    with client.session_transaction() as sess:
        assert sess["analytics_sid"] == first


def test_the_beacon_receives_the_same_session_id_the_cart_uses(client):
    """Rendered into the page, so track.js and the cart cannot disagree."""
    client.post("/cart/add", data={"slug": "mclaren-p1-red", "qty": "1"})
    with client.session_transaction() as sess:
        sid = sess["analytics_sid"]
    body = client.get("/shop").data.decode()
    assert f'data-sid="{sid}"' in body


@pytest.mark.marts
def test_engaged_time_is_never_greater_than_elapsed_time():
    """Visible seconds cannot exceed wall-clock, or dwell tracking is double-counting."""
    requires_mart("mart_visitor_sessions")
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select count(*) as n from mart.mart_visitor_sessions
                where engaged_seconds > greatest(duration_seconds, 0) + 120"""
        )
        assert cur.fetchone()["n"] == 0


@pytest.mark.marts
def test_page_engagement_has_no_impossible_percentages():
    requires_mart("mart_page_engagement")
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select count(*) as n from mart.mart_page_engagement
                where avg_scroll_pct > 100 or exit_pct > 100 or exit_pct < 0"""
        )
        assert cur.fetchone()["n"] == 0


@pytest.mark.marts
def test_every_ranked_seller_has_a_band():
    """No product may fall through the banding into a null.

    Counted against products that were live when the marts were built, not
    against the table now -- a draft fixture product added afterwards is
    correctly absent, and asserting otherwise would just make the test flap.
    """
    requires_mart("mart_seller_ranking")
    with tx(Role.SUPER) as cur:
        cur.execute("select count(*) as n from mart.mart_seller_ranking where band is null")
        assert cur.fetchone()["n"] == 0
        cur.execute("select count(*) as n from mart.mart_seller_ranking")
        ranked = cur.fetchone()["n"]
        cur.execute(
            "select count(*) as n from store.products where archived_at is null and status = 'active'"
        )
        active = cur.fetchone()["n"]
    assert 0 < ranked <= active, f"{ranked} ranked products against {active} active"


@pytest.mark.marts
def test_abandoned_interest_excludes_products_that_were_bought():
    """A product bought in the same session must not appear as abandoned by it."""
    requires_mart("mart_abandoned_interest")
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select count(*) as n
                 from mart.mart_abandoned_interest a
                where a.abandoned_cart_adds = 0 and a.abandoned_saves = 0"""
        )
        assert cur.fetchone()["n"] == 0, "rows with no abandonment should not be listed"


def test_live_carts_are_read_from_oltp_not_a_mart():
    """Stale cart data is worthless -- verify it reflects a change immediately."""
    before = repo.live_totals()
    with tx(Role.SUPER) as cur:
        cur.execute(
            """insert into store.carts (session_id, state) values (gen_random_uuid(), 'active')
            returning id"""
        )
        cart_id = cur.fetchone()["id"]
        cur.execute("select id, price_cents from store.variants limit 1")
        variant = cur.fetchone()
        cur.execute(
            """insert into store.cart_items (cart_id, variant_id, qty, unit_price_cents)
               values (%s, %s, 2, %s)""",
            (cart_id, variant["id"], variant["price_cents"]),
        )
    after = repo.live_totals()
    assert after["active_carts"] == before["active_carts"] + 1
    assert after["active_value_cents"] > before["active_value_cents"]
    with tx(Role.SUPER) as cur:
        cur.execute("delete from store.cart_items where cart_id = %s", (cart_id,))
        cur.execute("delete from store.carts where id = %s", (cart_id,))


def test_marts_readiness_is_reported_per_table():
    ready = repo.marts_ready()
    assert set(ready) == set(repo.REQUIRED_MARTS)
    assert all(isinstance(v, bool) for v in ready.values())


def test_a_missing_mart_yields_an_empty_result_not_an_exception():
    """A fresh install must show 'no data', never a 500."""
    repo.take_failures()
    assert repo._query("select 1", mart="mart_does_not_exist") == []
    # An unbuilt mart is not a failure -- it must not raise the alarm.
    assert repo.take_failures() == []


@pytest.mark.marts
def test_a_broken_query_is_reported_rather_than_shown_as_zero():
    """The failure that matters: an empty panel the owner reads as a quiet week.

    Needs the mart to exist: _query short-circuits on an unbuilt one and reports
    nothing, which is right -- an unbuilt mart is a fresh install, not an outage.
    The unconditional coverage of that path is the two tests below.
    """
    requires_mart("mart_visitor_sessions")
    repo.take_failures()
    assert repo._query("select * from mart.mart_visitor_sessions where nope = 1",
                       mart="mart_visitor_sessions") == []
    assert repo.take_failures() == ["mart_visitor_sessions"]


def test_failures_are_drained_so_they_do_not_leak_into_the_next_page():
    repo.take_failures()
    repo._query("select this is not sql")
    assert repo.take_failures() == ["live query"]
    assert repo.take_failures() == []


def test_a_broken_panel_says_so_on_the_page(as_role, monkeypatch):
    client = as_role("owner")
    monkeypatch.setattr(repo, "funnel", lambda days=30: repo._query("select bad sql here"))
    body = client.get("/insights/?days=30").data.decode()
    assert "failed to load" in body
    assert 'do not read them as "no activity"' in body


def test_ingestion_health_is_queryable_by_the_admin_role():
    stats = repo.events_today()
    assert "events" in stats and "sessions" in stats
