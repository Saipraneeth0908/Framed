"""Server-side carts.

The browser cookie holds only ``cart_token`` (a uuid). Quantities, variants and
prices live in store.cart_items, so a customer cannot edit a price by editing a
cookie -- the old session-list cart could be tampered with the moment the
secret leaked.
"""

from __future__ import annotations

from db.conn import Role, tx
from web.pricing import config_price_cents

MAX_QTY = 25


def create(session_id: str | None = None) -> str:
    with tx(Role.STORE) as cur:
        cur.execute(
            "insert into store.carts (session_id) values (%s) returning public_id::text as token",
            (session_id,),
        )
        return cur.fetchone()["token"]


def items(token: str) -> list[dict]:
    """Line items in the legacy dict shape the templates and totals expect."""
    with tx(Role.STORE) as cur:
        cur.execute(
            """
            select ci.id, ci.qty, ci.poster_theme, ci.unit_price_cents,
                   v.id as variant_id, v.frame, v.size,
                   p.slug::text as slug, p.name
              from store.cart_items ci
              join store.carts c    on c.id = ci.cart_id
              join store.variants v on v.id = ci.variant_id
              join store.products p on p.id = v.product_id
             where c.public_id = %s
             order by ci.id
            """,
            (token,),
        )
        return [
            {
                "id": r["id"],
                "slug": r["slug"],
                "qty": r["qty"],
                "variant_id": r["variant_id"],
                "config": {"frame": r["frame"], "size": r["size"], "poster_theme": r["poster_theme"]},
                "unit_price": r["unit_price_cents"] / 100,
            }
            for r in cur.fetchall()
        ]


def add(token: str, slug: str, config: dict, qty: int, unit_cents: int) -> None:
    with tx(Role.STORE) as cur:
        cur.execute(
            """select v.id from store.variants v join store.products p on p.id = v.product_id
                where p.slug = %s and v.frame = %s and v.size = %s
                  and v.archived_at is null and p.archived_at is null""",
            (slug, config["frame"], config["size"]),
        )
        row = cur.fetchone()
        if not row:
            return
        cur.execute(
            """
            insert into store.cart_items (cart_id, variant_id, poster_theme, qty, unit_price_cents)
            select c.id, %s, %s, %s, %s from store.carts c where c.public_id = %s
            on conflict (cart_id, variant_id, poster_theme) do update
              -- least(): the qty column is capped at 25 by a check constraint,
              -- so an unbounded increment would 500 instead of clamping.
              set qty = least(store.cart_items.qty + excluded.qty, %s),
                  unit_price_cents = excluded.unit_price_cents
            """,
            (row["id"], config["poster_theme"], qty, unit_cents, token, MAX_QTY),
        )
        _touch(cur, token)


def update_by_index(token: str, index: int, qty: int) -> None:
    """cart.html posts a positional index; ordering is by id, same as items()."""
    if index < 0:
        return
    with tx(Role.STORE) as cur:
        cur.execute(
            """select ci.id from store.cart_items ci join store.carts c on c.id = ci.cart_id
                where c.public_id = %s order by ci.id offset %s limit 1""",
            (token, index),
        )
        row = cur.fetchone()
        if not row:
            return
        if qty <= 0:
            cur.execute("delete from store.cart_items where id = %s", (row["id"],))
        else:
            cur.execute(
                "update store.cart_items set qty = %s where id = %s", (min(qty, MAX_QTY), row["id"])
            )
        _touch(cur, token)


def clear(token: str) -> None:
    with tx(Role.STORE) as cur:
        cur.execute(
            """delete from store.cart_items
                where cart_id = (select id from store.carts where public_id = %s)""",
            (token,),
        )
        _touch(cur, token)


def reprice(token: str) -> None:
    """Refresh stored unit prices from the live catalog (called before checkout)."""
    with tx(Role.STORE) as cur:
        cur.execute(
            """select ci.id, ci.poster_theme, v.price_cents, v.sale_price_cents
                 from store.cart_items ci
                 join store.carts c on c.id = ci.cart_id
                 join store.variants v on v.id = ci.variant_id
                where c.public_id = %s""",
            (token,),
        )
        rows = cur.fetchall()
        cur.execute("select key, add_cents from store.poster_themes")
        theme_add = {r["key"]: r["add_cents"] for r in cur.fetchall()}
        for r in rows:
            base = r["sale_price_cents"] or r["price_cents"]
            cur.execute(
                "update store.cart_items set unit_price_cents = %s where id = %s",
                (base + theme_add.get(r["poster_theme"], 0), r["id"]),
            )


def _touch(cur, token: str) -> None:
    cur.execute("update store.carts set last_activity_at = now() where public_id = %s", (token,))


__all__ = ["create", "items", "add", "update_by_index", "clear", "reprice", "config_price_cents"]
