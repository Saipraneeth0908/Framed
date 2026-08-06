"""Order placement, reservation and the transactional outbox.

Every write below happens in ONE transaction: order, line items, inventory
ledger and the outbox row. There is no second write that can fail on its own, so
analytics can never disagree with the ledger. That is the whole reason the
outbox exists rather than a publish-after-commit call.
"""

from __future__ import annotations

import json
import logging

from psycopg import errors

from db.conn import Role, tx
from web.pricing import BUNDLE_MIN_QTY, BUNDLE_PERCENT

log = logging.getLogger(__name__)


class OutOfStock(Exception):
    """Raised when reserving components would push reserved past on_hand."""


def _emit(cur, topic: str, payload: dict) -> None:
    cur.execute(
        "insert into raw.outbox (topic, payload) values (%s, %s)",
        (topic, json.dumps(payload, default=str)),
    )


def _upsert_customer(cur, data: dict) -> int:
    cur.execute(
        """
        insert into store.customers (email, name, phone)
        values (%s, %s, %s)
        on conflict (email) where archived_at is null
          do update set name = coalesce(excluded.name, store.customers.name),
                        phone = coalesce(excluded.phone, store.customers.phone)
        returning id
        """,
        (data["email"], data.get("name"), data.get("phone") or None),
    )
    return cur.fetchone()["id"]


def place_order(cart_token: str, data: dict, items: list[dict]) -> dict:
    """Create the order from the server-side cart, then take payment.

    Prices are re-derived from store.variants inside the transaction. Nothing
    the customer posted contributes to the amount charged.
    """
    from web.payments import gateway

    with tx(Role.STORE) as cur:
        cur.execute("select id from store.carts where public_id = %s for update", (cart_token,))
        cart = cur.fetchone()
        if not cart:
            raise OutOfStock("Your cart expired. Please add your posters again.")

        cur.execute("select key, add_cents from store.poster_themes")
        theme_add = {r["key"]: r["add_cents"] for r in cur.fetchall()}

        lines, subtotal = [], 0
        for item in items:
            cur.execute(
                """
                select v.id as variant_id, v.sku, v.price_cents, v.sale_price_cents, v.frame, v.size,
                       p.id as product_id, p.name,
                       coalesce((select sum(c.unit_cost_cents * vc.qty)
                                   from ops.variant_components vc
                                   join ops.components c on c.id = vc.component_id
                                  where vc.variant_id = v.id), 0) as cost_cents
                  from store.variants v join store.products p on p.id = v.product_id
                 where v.id = %s
                """,
                (item["variant_id"],),
            )
            v = cur.fetchone()
            if not v:
                continue
            unit = (v["sale_price_cents"] or v["price_cents"]) + theme_add.get(
                item["config"]["poster_theme"], 0
            )
            subtotal += unit * item["qty"]
            lines.append((v, item, unit))

        total_qty = sum(i["qty"] for i in items)
        discount = round(subtotal * BUNDLE_PERCENT / 100) if total_qty >= BUNDLE_MIN_QTY else 0

        cur.execute(
            """
            insert into store.orders
              (customer_id, cart_id, email, phone, subtotal_cents, discount_cents, total_cents,
               ship_name, ship_street, ship_unit, ship_city, ship_state, ship_zip, ship_country,
               ship_instructions)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            returning id, public_id::text as public_id, order_no, total_cents
            """,
            (
                _upsert_customer(cur, data), cart["id"], data["email"], data.get("phone") or None,
                subtotal, discount, subtotal - discount,
                data.get("name"), data.get("street"), data.get("unit") or None, data.get("city"),
                data.get("state"), data.get("zip"), data.get("country") or "United States",
                data.get("instructions") or None,
            ),
        )
        order = cur.fetchone()

        for v, item, unit in lines:
            cur.execute(
                """
                insert into store.order_items
                  (order_id, variant_id, product_id, sku_snapshot, name_snapshot, attrs_snapshot,
                   qty, unit_price_cents, cost_cents)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    order["id"], v["variant_id"], v["product_id"], v["sku"], v["name"],
                    json.dumps({"frame": v["frame"], "size": v["size"],
                                "poster_theme": item["config"]["poster_theme"]}),
                    item["qty"], unit, v["cost_cents"],
                ),
            )

        cur.execute(
            "update store.carts set state = 'converted', converted_at = now() where id = %s",
            (cart["id"],),
        )
        _emit(cur, "order.placed", {
            "order_id": order["id"], "order_no": order["order_no"],
            "total_cents": order["total_cents"], "qty": total_qty,
        })

    result = dict(order)
    result.update(gateway().charge(order["id"], order["total_cents"], data["email"]))
    return result


def mark_paid(order_id: int, payment_ref: str | None = None, actor_id: int | None = None) -> None:
    """Flip to paid and reserve the components. Reserve-on-paid, consume-on-production.

    Idempotent: a Stripe webhook that fires twice must not reserve twice.
    """
    with tx(Role.STORE, actor_id=actor_id) as cur:
        cur.execute(
            """update store.orders set payment_status = 'paid', paid_at = now(),
                      stripe_payment_intent = coalesce(%s, stripe_payment_intent)
                where id = %s and payment_status <> 'paid'
             returning id, order_no, total_cents""",
            (payment_ref, order_id),
        )
        order = cur.fetchone()
        if not order:
            return                                     # already paid; nothing to do

        try:
            cur.execute(
                """
                insert into ops.inventory_ledger (component_id, reserved_delta, reason, order_item_id, note)
                select vc.component_id, vc.qty * oi.qty, 'reserve', oi.id, 'reserved on payment'
                  from store.order_items oi
                  join ops.variant_components vc on vc.variant_id = oi.variant_id
                 where oi.order_id = %s
                """,
                (order_id,),
            )
        except errors.CheckViolation as exc:
            raise OutOfStock(
                "One of these frames just sold out while you were checking out. "
                "Your card has not been charged."
            ) from exc

        _emit(cur, "order.paid", {
            "order_id": order["id"], "order_no": order["order_no"], "total_cents": order["total_cents"],
        })


def consume_for_item(order_item_id: int, actor_id: int | None = None) -> None:
    """Reserved -> gone. Called when a line item enters the 'printing' station."""
    with tx(Role.ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """
            insert into ops.inventory_ledger
              (component_id, delta, reserved_delta, reason, order_item_id, actor_id, note)
            select vc.component_id, -(vc.qty * oi.qty), -(vc.qty * oi.qty), 'consume', oi.id, %s,
                   'consumed at production start'
              from store.order_items oi
              join ops.variant_components vc on vc.variant_id = oi.variant_id
             where oi.id = %s
               and not exists (select 1 from ops.inventory_ledger l
                                where l.order_item_id = oi.id and l.reason = 'consume')
            """,
            (actor_id, order_item_id),
        )


def restock_for_item(order_item_id: int, reason: str, actor_id: int | None = None) -> None:
    """Cancel or return: put the components back, undoing whichever step happened."""
    with tx(Role.ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """select coalesce(sum(delta), 0) as d, coalesce(sum(reserved_delta), 0) as r
                 from ops.inventory_ledger where order_item_id = %s""",
            (order_item_id,),
        )
        net = cur.fetchone()
        cur.execute(
            """
            insert into ops.inventory_ledger
              (component_id, delta, reserved_delta, reason, order_item_id, actor_id, note)
            select vc.component_id,
                   case when %s < 0 then vc.qty * oi.qty else 0 end,
                   case when %s > 0 then -(vc.qty * oi.qty) else 0 end,
                   %s, oi.id, %s, 'restock'
              from store.order_items oi
              join ops.variant_components vc on vc.variant_id = oi.variant_id
             where oi.id = %s
            """,
            (net["d"], net["r"], reason, actor_id, order_item_id),
        )
