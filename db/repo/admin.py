"""Admin queries.

Everything here runs as admin_app. Aggregate-heavy and written as plain SQL on
purpose: these are the queries an ORM makes worse, and the same SQL is readable
by whoever is looking at the equivalent Metabase question.
"""

from __future__ import annotations

import json

from db.conn import Role, tx

ADMIN = Role.ADMIN


# --------------------------------------------------------------------------- #
# Action board -- what needs a human today, in one round trip.
# --------------------------------------------------------------------------- #

ACTION_BOARD_SQL = """
select
  (select count(*) from store.orders
    where payment_status = 'paid' and fulfilment_status = 'unfulfilled'
      and cancelled_at is null)                                        as to_fulfil,
  (select count(*) from store.order_items where production_status = 'blocked') as blocked_items,
  (select count(*) from store.orders o
    where o.payment_status = 'paid' and o.fulfilment_status = 'unfulfilled'
      and o.cancelled_at is null
      and o.placed_at < now() - (%(stuck_hours)s || ' hours')::interval) as stuck_orders,
  (select count(*) from ops.components_low)                            as low_components,
  (select count(*) from store.carts
    where state = 'active' and last_activity_at < now() - interval '30 minutes') as stale_carts,
  (select coalesce(sum(ci.qty * ci.unit_price_cents), 0) from store.cart_items ci
     join store.carts c on c.id = ci.cart_id
    where c.state = 'abandoned' and c.abandoned_at > now() - interval '24 hours') as abandoned_cents,
  (select count(*) from store.orders where payment_status = 'failed'
     and placed_at > now() - interval '1 hour')                        as payment_failures,
  (select count(*) from ops.ledger_drift())                            as ledger_drift
"""


def action_board(stuck_hours: int = 24) -> dict:
    with tx(ADMIN) as cur:
        cur.execute(ACTION_BOARD_SQL, {"stuck_hours": stuck_hours})
        return cur.fetchone()


def kpis() -> dict:
    with tx(ADMIN) as cur:
        cur.execute(
            """
            select
              coalesce(sum(total_cents) filter (where placed_at::date = current_date), 0) as revenue_today,
              coalesce(sum(total_cents) filter (where placed_at > now() - interval '7 days'), 0) as revenue_7d,
              count(*) filter (where placed_at::date = current_date)                     as orders_today,
              count(*) filter (where placed_at > now() - interval '7 days')              as orders_7d,
              coalesce(round(avg(total_cents) filter (where placed_at > now() - interval '30 days')), 0) as aov_30d
              from store.orders where payment_status in ('paid', 'partially_refunded')
            """
        )
        row = cur.fetchone()
        cur.execute(
            """select coalesce(sum(oi.qty * (oi.unit_price_cents - oi.cost_cents)), 0) as margin_30d
                 from store.order_items oi join store.orders o on o.id = oi.order_id
                where o.paid_at > now() - interval '30 days'"""
        )
        row.update(cur.fetchone())
        return row


def revenue_sparkline(days: int = 30) -> list[dict]:
    with tx(ADMIN) as cur:
        cur.execute(
            """
            select d::date as day, coalesce(sum(o.total_cents), 0) as cents
              from generate_series(current_date - (%s - 1), current_date, interval '1 day') d
              left join store.orders o
                on o.placed_at::date = d::date and o.payment_status in ('paid', 'partially_refunded')
             group by d order by d
            """,
            (days,),
        )
        return cur.fetchall()


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #

def orders(status: str = "", query: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    clauses, params = ["1=1"], {"limit": limit, "offset": offset}
    if status == "to_fulfil":
        clauses.append("o.payment_status = 'paid' and o.fulfilment_status = 'unfulfilled' and o.cancelled_at is null")
    elif status == "unpaid":
        clauses.append("o.payment_status = 'unpaid'")
    elif status == "refunded":
        clauses.append("o.payment_status in ('refunded', 'partially_refunded')")
    elif status == "cancelled":
        clauses.append("o.cancelled_at is not null")
    if query:
        clauses.append("(o.order_no ilike %(q)s or o.email::text ilike %(q)s or o.ship_name ilike %(q)s)")
        params["q"] = f"%{query}%"
    with tx(ADMIN) as cur:
        cur.execute(
            f"""
            select o.id, o.order_no, o.email::text as email, o.ship_name, o.placed_at,
                   o.payment_status::text as payment_status,
                   o.fulfilment_status::text as fulfilment_status,
                   o.production_rollup::text as production_rollup,
                   o.total_cents, o.refunded_cents, o.cancelled_at,
                   (select count(*) from store.order_items i where i.order_id = o.id) as line_count
              from store.orders o
             where {' and '.join(clauses)}
             order by o.placed_at desc
             limit %(limit)s offset %(offset)s
            """,
            params,
        )
        return cur.fetchall()


def order(order_id: int) -> dict | None:
    with tx(ADMIN) as cur:
        cur.execute(
            """select o.*, o.payment_status::text as payment_status_t,
                      o.fulfilment_status::text as fulfilment_status_t,
                      o.production_rollup::text as production_rollup_t,
                      c.public_id::text as customer_public_id
                 from store.orders o
                 left join store.customers c on c.id = o.customer_id
                where o.id = %s""",
            (order_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            """select id, sku_snapshot, name_snapshot, attrs_snapshot, qty, unit_price_cents,
                      cost_cents, refunded_qty, production_status::text as production_status,
                      blocked_reason, station_started_at
                 from store.order_items where order_id = %s order by id""",
            (order_id,),
        )
        row["items"] = cur.fetchall()
        cur.execute(
            "select * from store.refunds where order_id = %s order by created_at desc", (order_id,)
        )
        row["refunds"] = cur.fetchall()
        cur.execute(
            "select * from store.shipments where order_id = %s order by shipped_at desc", (order_id,)
        )
        row["shipments"] = cur.fetchall()
        return row


def set_fulfilment(order_id: int, status: str, actor_id: int) -> None:
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            "update store.orders set fulfilment_status = %s::fulfil_status where id = %s",
            (status, order_id),
        )


def add_shipment(order_id: int, carrier: str, tracking: str, url: str, actor_id: int) -> None:
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """insert into store.shipments (order_id, carrier, tracking_no, tracking_url, actor_id)
               values (%s,%s,%s,%s,%s)""",
            (order_id, carrier, tracking, url, actor_id),
        )
        cur.execute(
            "update store.orders set fulfilment_status = 'in_transit' where id = %s", (order_id,)
        )


def cancel_order(order_id: int, reason: str, actor_id: int) -> None:
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """update store.orders set cancelled_at = now(), cancel_reason = %s
                where id = %s and cancelled_at is null""",
            (reason, order_id),
        )
        cur.execute(
            """update store.order_items set production_status = 'cancelled'
                where order_id = %s and production_status <> 'packed'""",
            (order_id,),
        )
        cur.execute(
            "insert into raw.outbox (topic, payload) values ('order.cancelled', %s)",
            (json.dumps({"order_id": order_id, "reason": reason}),),
        )


def refund(order_id: int, order_item_id: int | None, amount_cents: int, qty: int | None,
           reason: str, restock: bool, actor_id: int) -> None:
    """Money back. History is never edited -- a refund is a new row."""
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """insert into store.refunds (order_id, order_item_id, amount_cents, qty, reason,
                                          restocked, actor_id)
               values (%s,%s,%s,%s,%s,%s,%s)""",
            (order_id, order_item_id, amount_cents, qty, reason, restock, actor_id),
        )
        if order_item_id and qty:
            cur.execute(
                "update store.order_items set refunded_qty = refunded_qty + %s where id = %s",
                (qty, order_item_id),
            )
        cur.execute(
            """update store.orders
                  set refunded_cents = refunded_cents + %s,
                      payment_status = case when refunded_cents + %s >= total_cents
                                            then 'refunded'::payment_status
                                            else 'partially_refunded'::payment_status end
                where id = %s""",
            (amount_cents, amount_cents, order_id),
        )
        cur.execute(
            "insert into raw.outbox (topic, payload) values ('order.refunded', %s)",
            (json.dumps({"order_id": order_id, "amount_cents": amount_cents, "reason": reason}),),
        )


# --------------------------------------------------------------------------- #
# Production board
# --------------------------------------------------------------------------- #

STATION_ORDER = ["queued", "printing", "printed", "mounting", "framing", "qc", "packed"]
NEXT_STATION = dict(zip(STATION_ORDER, STATION_ORDER[1:]))


def production_board() -> dict[str, list[dict]]:
    with tx(ADMIN) as cur:
        cur.execute(
            """
            select oi.id, oi.production_status::text as status, oi.qty, oi.sku_snapshot,
                   oi.name_snapshot, oi.attrs_snapshot, oi.blocked_reason, oi.station_started_at,
                   o.id as order_id, o.order_no, o.placed_at, o.ship_name
              from store.order_items oi
              join store.orders o on o.id = oi.order_id
             where oi.production_status not in ('packed', 'cancelled')
               and o.payment_status in ('paid', 'partially_refunded')
               and o.cancelled_at is null
             order by o.placed_at, oi.id
            """
        )
        board: dict[str, list[dict]] = {s: [] for s in STATION_ORDER + ["blocked", "reprint"]}
        for row in cur.fetchall():
            board.setdefault(row["status"], []).append(row)
        return board


def advance_item(item_id: int, to_status: str, actor_id: int, reason: str = "") -> str:
    """Move one line item to the next station. Illegal transitions return 409.

    Consumption happens exactly once, when the item first reaches 'printing'.
    """
    from web.orders import consume_for_item

    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            "select production_status::text as s, order_id from store.order_items where id = %s for update",
            (item_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(item_id)
        current = row["s"]
        allowed = {NEXT_STATION.get(current), "blocked", "cancelled", "reprint"}
        if current == "blocked":
            allowed |= set(STATION_ORDER)
        if current == "reprint":
            allowed |= {"printing"}
        if to_status not in allowed - {None}:
            raise ValueError(f"{current} -> {to_status} is not a legal transition")
        cur.execute(
            """update store.order_items
                  set production_status = %s::prod_status,
                      station_started_at = now(),
                      blocked_reason = case when %s = 'blocked' then %s else null end
                where id = %s""",
            (to_status, to_status, reason or None, item_id),
        )
    if to_status == "printing":
        consume_for_item(item_id, actor_id=actor_id)
    return to_status


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #

def components(kind: str = "", low_only: bool = False) -> list[dict]:
    clauses, params = ["c.archived_at is null"], {}
    if kind:
        clauses.append("c.kind = %(kind)s")
        params["kind"] = kind
    if low_only:
        clauses.append("(c.on_hand - c.reserved) <= c.low_threshold")
    with tx(ADMIN) as cur:
        cur.execute(
            f"""select c.*, (c.on_hand - c.reserved) as available,
                       (select count(*) from ops.variant_components vc where vc.component_id = c.id) as used_by
                  from ops.components c
                 where {' and '.join(clauses)}
                 order by (c.on_hand - c.reserved) <= c.low_threshold desc, c.kind, c.sku""",
            params,
        )
        return cur.fetchall()


def component(component_id: int) -> dict | None:
    with tx(ADMIN) as cur:
        cur.execute(
            "select *, (on_hand - reserved) as available from ops.components where id = %s",
            (component_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            """select l.*, u.name as actor_name, oi.sku_snapshot
                 from ops.inventory_ledger l
                 left join ops.users u on u.id = l.actor_id
                 left join store.order_items oi on oi.id = l.order_item_id
                where l.component_id = %s order by l.created_at desc limit 200""",
            (component_id,),
        )
        row["ledger"] = cur.fetchall()
        return row


def adjust_stock(component_id: int, delta: int, reason: str, note: str, actor_id: int) -> None:
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """insert into ops.inventory_ledger (component_id, delta, reason, actor_id, note)
               values (%s,%s,%s::adj_reason,%s,%s)""",
            (component_id, delta, reason, actor_id, note or None),
        )


def reorder_list() -> list[dict]:
    with tx(ADMIN) as cur:
        cur.execute(
            """select sku, name, kind, on_hand, reserved, (on_hand - reserved) as available,
                      low_threshold, supplier, lead_days, unit_cost_cents,
                      greatest(low_threshold * 3 - (on_hand - reserved), 0) as suggested_qty
                 from ops.components
                where archived_at is null and (on_hand - reserved) <= low_threshold
                order by (on_hand - reserved) - low_threshold, sku"""
        )
        return cur.fetchall()


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

def products(query: str = "", category: str = "", include_archived: bool = False) -> list[dict]:
    clauses, params = ([] if include_archived else ["p.archived_at is null"]), {}
    if query:
        clauses.append("(p.name ilike %(q)s or p.slug::text ilike %(q)s or p.brand ilike %(q)s)")
        params["q"] = f"%{query}%"
    if category:
        clauses.append("p.category = %(cat)s")
        params["cat"] = category
    where = " and ".join(clauses) or "1=1"
    with tx(ADMIN) as cur:
        cur.execute(
            f"""select p.id, p.slug::text as slug, p.name, p.brand, p.category,
                       p.status::text as status, p.featured, p.position, p.base_price_cents,
                       p.archived_at,
                       (select count(*) from store.variants v
                         where v.product_id = p.id and v.archived_at is null) as variant_count,
                       (select url from store.product_images i
                         where i.product_id = p.id and i.role = 'poster' limit 1) as poster
                  from store.products p where {where}
                 order by p.position, p.id""",
            params,
        )
        return cur.fetchall()


def product(product_id: int) -> dict | None:
    with tx(ADMIN) as cur:
        cur.execute(
            """select p.*, p.status::text as status_t, p.slug::text as slug_t
                 from store.products p where p.id = %s""",
            (product_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            """select v.*, v.status::text as status_t,
                      coalesce(b.buildable, 0) as buildable
                 from store.variants v
                 left join ops.variant_buildable b on b.variant_id = v.id
                where v.product_id = %s order by v.position, v.id""",
            (product_id,),
        )
        row["variants"] = cur.fetchall()
        cur.execute(
            "select * from store.product_images where product_id = %s order by role, position",
            (product_id,),
        )
        row["images"] = cur.fetchall()
        cur.execute(
            "select tag::text as tag, position from store.product_tags where product_id = %s order by position",
            (product_id,),
        )
        row["tags"] = cur.fetchall()
        return row


def update_product(product_id: int, fields: dict, actor_id: int) -> None:
    allowed = {"name", "brand", "series", "category", "color", "short_desc", "description",
               "status", "featured", "position", "base_price_cents"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    assignments = ", ".join(
        f"{k} = %({k})s::product_status" if k == "status" else f"{k} = %({k})s" for k in sets
    )
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            f"update store.products set {assignments} where id = %(id)s", {**sets, "id": product_id}
        )


def update_variant(variant_id: int, price_cents: int, sale_cents: int | None, status: str,
                   actor_id: int) -> None:
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """update store.variants
                  set price_cents = %s, sale_price_cents = %s, status = %s::product_status
                where id = %s""",
            (price_cents, sale_cents, status, variant_id),
        )


def bulk_update_variants(rows: list[dict], actor_id: int) -> dict:
    """Apply price/status changes keyed by SKU.

    Used by both the CSV import and the bulk-edit form. Unknown SKUs are
    reported rather than ignored: a silent no-op on a typo'd SKU is how a price
    change goes out half-applied.
    """
    applied, unknown, rejected = 0, [], []
    with tx(ADMIN, actor_id=actor_id) as cur:
        for row in rows:
            sku = (row.get("sku") or "").strip()
            if not sku:
                continue
            sets, params = [], {"sku": sku}
            if row.get("price_cents") is not None:
                if row["price_cents"] < 0:
                    rejected.append(f"{sku}: negative price")
                    continue
                sets.append("price_cents = %(price_cents)s")
                params["price_cents"] = row["price_cents"]
            if "sale_price_cents" in row:
                sets.append("sale_price_cents = %(sale_price_cents)s")
                params["sale_price_cents"] = row["sale_price_cents"]
            if row.get("status"):
                if row["status"] not in {"draft", "active", "archived"}:
                    rejected.append(f"{sku}: unknown status {row['status']}")
                    continue
                sets.append("status = %(status)s::product_status")
                params["status"] = row["status"]
            if not sets:
                continue
            cur.execute(
                f"update store.variants set {', '.join(sets)} "
                "where sku = %(sku)s and archived_at is null returning id",
                params,
            )
            if cur.fetchone():
                applied += 1
            else:
                unknown.append(sku)
    return {"applied": applied, "unknown": unknown, "rejected": rejected}


def bulk_update_products(product_ids: list[int], fields: dict, actor_id: int) -> int:
    allowed = {"status", "featured", "category"}
    sets = {k: v for k, v in fields.items() if k in allowed and v not in (None, "")}
    if not sets or not product_ids:
        return 0
    assignments = ", ".join(
        f"{k} = %({k})s::product_status" if k == "status" else f"{k} = %({k})s" for k in sets
    )
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            f"update store.products set {assignments} where id = any(%(ids)s) and archived_at is null",
            {**sets, "ids": product_ids},
        )
        return cur.rowcount


def variants_for_export() -> list[dict]:
    with tx(ADMIN) as cur:
        cur.execute(
            """select v.sku, p.slug::text as product_slug, p.name as product_name,
                      v.frame, v.size, v.price_cents, v.sale_price_cents,
                      v.status::text as status
                 from store.variants v join store.products p on p.id = v.product_id
                where v.archived_at is null order by p.position, v.position"""
        )
        return cur.fetchall()


def archive_product(product_id: int, actor_id: int) -> None:
    """Archive, never delete: orders reference these rows and reports need them."""
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute("update store.products set archived_at = now(), status = 'archived' where id = %s",
                    (product_id,))
        cur.execute("update store.variants set archived_at = now() where product_id = %s", (product_id,))


# --------------------------------------------------------------------------- #
# Customers, discounts, settings, audit
# --------------------------------------------------------------------------- #

def customers(query: str = "", limit: int = 100) -> list[dict]:
    clause, params = "c.archived_at is null", {"limit": limit}
    if query:
        clause += " and (c.email::text ilike %(q)s or c.name ilike %(q)s)"
        params["q"] = f"%{query}%"
    with tx(ADMIN) as cur:
        cur.execute(
            f"""select c.id, c.email::text as email, c.name, c.created_at,
                       count(o.id) filter (where o.payment_status in ('paid','partially_refunded')) as orders,
                       coalesce(sum(o.total_cents) filter (where o.payment_status in ('paid','partially_refunded')), 0) as ltv_cents,
                       max(o.placed_at) as last_order_at
                  from store.customers c
                  left join store.orders o on o.customer_id = c.id
                 where {clause}
                 group by c.id order by ltv_cents desc limit %(limit)s""",
            params,
        )
        return cur.fetchall()


def discounts() -> list[dict]:
    with tx(ADMIN) as cur:
        cur.execute(
            """select id, code::text as code, kind::text as kind, value, min_subtotal_cents,
                      starts_at, ends_at, max_redemptions, redemptions, active
                 from store.discounts where archived_at is null order by created_at desc"""
        )
        return cur.fetchall()


def create_discount(code: str, kind: str, value: int, min_subtotal_cents: int,
                    max_redemptions: int | None, actor_id: int) -> None:
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """insert into store.discounts (code, kind, value, min_subtotal_cents, max_redemptions)
               values (%s, %s::discount_kind, %s, %s, %s)""",
            (code, kind, value, min_subtotal_cents, max_redemptions),
        )


def settings() -> dict:
    with tx(ADMIN) as cur:
        cur.execute("select key, value from ops.settings order by key")
        return {r["key"]: r["value"] for r in cur.fetchall()}


def set_setting(key: str, value, actor_id: int) -> None:
    with tx(ADMIN, actor_id=actor_id) as cur:
        cur.execute(
            """insert into ops.settings (key, value, updated_by, updated_at)
               values (%s, %s, %s, now())
               on conflict (key) do update set value = excluded.value,
                                               updated_by = excluded.updated_by,
                                               updated_at = now()""",
            (key, json.dumps(value), actor_id),
        )


def users() -> list[dict]:
    with tx(ADMIN) as cur:
        cur.execute(
            """select id, email::text as email, name, role::text as role, totp_enabled,
                      last_login_at, locked_until, archived_at
                 from ops.users order by archived_at nulls first, name"""
        )
        return cur.fetchall()


def audit_log(entity: str = "", actor_id: int | None = None, limit: int = 200) -> list[dict]:
    clauses, params = ["1=1"], {"limit": limit}
    if entity:
        clauses.append("a.entity = %(entity)s")
        params["entity"] = entity
    if actor_id:
        clauses.append("a.actor_id = %(actor)s")
        params["actor"] = actor_id
    with tx(ADMIN) as cur:
        cur.execute(
            f"""select a.id, a.action, a.entity, a.entity_id, a.created_at, a.request_id,
                       a.before, a.after, u.name as actor_name, u.email::text as actor_email
                  from ops.audit_log a left join ops.users u on u.id = a.actor_id
                 where {' and '.join(clauses)}
                 order by a.created_at desc limit %(limit)s""",
            params,
        )
        return cur.fetchall()


def mart_available() -> bool:
    """dbt marts may not exist yet; the analytics page degrades instead of 500ing."""
    with tx(ADMIN) as cur:
        cur.execute("select to_regclass('mart.mart_daily_kpis') is not null as ok")
        return bool(cur.fetchone()["ok"])
