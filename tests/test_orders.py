"""Sprint 1 acceptance: an order lands in Postgres, reserves components, and
stock_sane rejects an oversell.
"""

from __future__ import annotations

import pytest
from psycopg import errors

from db.conn import Role, tx


@pytest.fixture()
def placed_order(client):
    client.post("/cart/add", data={"slug": "mclaren-p1-red", "qty": "3", "frame": "walnut", "size": "A3"})
    response = client.post(
        "/checkout",
        data={
            "name": "Test Buyer", "email": "buyer@example.com", "street": "1 Track Way",
            "city": "Woking", "state": "CA", "zip": "94016", "country": "United States",
        },
    )
    assert response.status_code == 200
    assert b"Thank" in response.data or b"success" in response.data.lower()
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select id, order_no, payment_status::text as payment_status, total_cents,
                      subtotal_cents, discount_cents, production_rollup::text as rollup
                 from store.orders order by id desc limit 1"""
        )
        return cur.fetchone()


def test_order_lands_paid_with_frozen_snapshots(placed_order):
    assert placed_order["payment_status"] == "paid"
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select sku_snapshot, name_snapshot, attrs_snapshot, qty, unit_price_cents, cost_cents,
                      production_status::text as status
                 from store.order_items where order_id = %s""",
            (placed_order["id"],),
        )
        items = cur.fetchall()
    assert len(items) == 1
    line = items[0]
    assert line["qty"] == 3
    assert line["sku_snapshot"].endswith("-WAL-A3")
    assert line["attrs_snapshot"] == {"frame": "walnut", "size": "A3", "poster_theme": "racing_stripes"}
    # 89 base + 15 walnut + 12 A3 = $116.00, and the BOM cost is frozen alongside.
    assert line["unit_price_cents"] == 11600
    assert line["cost_cents"] > 0
    assert line["status"] == "queued"


def test_bundle_discount_is_applied_server_side(placed_order):
    assert placed_order["subtotal_cents"] == 34800
    assert placed_order["discount_cents"] == 3480
    assert placed_order["total_cents"] == 31320


def test_payment_reserves_components(placed_order):
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select count(*) as rows, sum(l.reserved_delta) as reserved
                 from ops.inventory_ledger l
                 join store.order_items oi on oi.id = l.order_item_id
                where oi.order_id = %s and l.reason = 'reserve'""",
            (placed_order["id"],),
        )
        row = cur.fetchone()
    assert row["rows"] == 5            # frame, paper, mount, glass, packaging
    assert row["reserved"] == 15       # 5 components x qty 3


def test_production_rollup_tracks_the_least_advanced_item(placed_order):
    assert placed_order["rollup"] == "queued"


def test_stock_sane_rejects_an_oversell():
    """Overselling is a database error, not a logic bug we hope we caught."""
    with pytest.raises(errors.CheckViolation):
        with tx(Role.SUPER) as cur:
            cur.execute("select id, on_hand from ops.components order by id limit 1")
            component = cur.fetchone()
            cur.execute(
                """insert into ops.inventory_ledger (component_id, reserved_delta, reason, note)
                   values (%s, %s, 'reserve', 'oversell attempt')""",
                (component["id"], component["on_hand"] + 1),
            )


def test_ledger_rows_cannot_be_edited():
    with pytest.raises(errors.RestrictViolation):
        with tx(Role.SUPER) as cur:
            cur.execute("update ops.inventory_ledger set delta = delta + 1 where id = (select min(id) from ops.inventory_ledger)")


def test_paid_order_items_are_frozen(placed_order):
    with pytest.raises(errors.RestrictViolation):
        with tx(Role.SUPER) as cur:
            cur.execute(
                "update store.order_items set unit_price_cents = 1 where order_id = %s",
                (placed_order["id"],),
            )


def test_production_status_stays_editable_on_a_paid_order(placed_order):
    with tx(Role.SUPER) as cur:
        cur.execute(
            "update store.order_items set production_status = 'printing' where order_id = %s",
            (placed_order["id"],),
        )
        cur.execute(
            "select production_rollup::text as r from store.orders where id = %s", (placed_order["id"],)
        )
        assert cur.fetchone()["r"] == "printing"


def test_outbox_recorded_the_order_in_the_same_transaction(placed_order):
    with tx(Role.SUPER) as cur:
        cur.execute(
            """select topic from raw.outbox
                where payload->>'order_id' = %s order by id""",
            (str(placed_order["id"]),),
        )
        topics = [r["topic"] for r in cur.fetchall()]
    assert topics == ["order.placed", "order.paid"]


def test_ledger_has_no_drift():
    with tx(Role.SUPER) as cur:
        cur.execute("select * from ops.ledger_drift()")
        assert cur.fetchall() == []
