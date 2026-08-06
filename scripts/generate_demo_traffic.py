"""Generate realistic demo traffic so the analytics dashboards can be judged.

    python -m scripts.generate_demo_traffic --days 45
    python -m scripts.generate_demo_traffic --purge     # remove all of it

Everything written here carries props.demo = true and orders carry a
'demo' internal_note, so a single --purge removes it and nothing else. This is
for evaluating the dashboards, not for pretending the shop has customers --
never run it against production.

The shapes are deliberately uneven: a diurnal and weekly rhythm, a long tail of
products nobody looks at, a few products people look at and never buy, and a
funnel that loses most of its traffic early. A generator that produces smooth
uniform data makes every chart look correct and teaches you nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.conn import Role, tx  # noqa: E402

DEMO_MARK = "demo"

SOURCES = [
    ("direct", None, 0.42), ("instagram", "l.instagram.com", 0.20),
    ("google", "www.google.com", 0.18), ("pinterest", "pinterest.com", 0.10),
    ("reddit", "old.reddit.com", 0.06), ("newsletter", None, 0.04),
]
DEVICES = [("mobile", 0.58), ("desktop", 0.34), ("tablet", 0.08)]
BROWSERS = [("chrome", 0.55), ("safari", 0.30), ("firefox", 0.09), ("edge", 0.06)]
COUNTRIES = [("US", 0.45), ("GB", 0.16), ("IN", 0.14), ("CA", 0.09), ("AU", 0.08), ("DE", 0.08)]

SEARCH_HITS = ["mclaren", "supercar", "anime", "nature", "kohli", "motivation", "poster", "frame"]
SEARCH_MISSES = ["lamborghini countach", "ferrari f40", "porsche 911", "batman", "star wars",
                 "formula 1", "ayrton senna", "vintage bike"]

# Weekday multipliers (Mon..Sun) and hour-of-day weights: evenings and weekends
# carry the traffic, which is what a consumer poster shop actually looks like.
DOW_WEIGHT = [0.85, 0.9, 0.95, 1.0, 1.25, 1.45, 1.3]
HOUR_WEIGHT = [0.2, 0.1, 0.08, 0.06, 0.06, 0.1, 0.25, 0.5, 0.7, 0.8, 0.85, 0.9,
               1.0, 0.95, 0.9, 0.9, 1.0, 1.2, 1.5, 1.7, 1.6, 1.3, 0.9, 0.5]


def weighted(options):
    total = sum(w for *_, w in options)
    roll = random.random() * total
    upto = 0.0
    for item in options:
        upto += item[-1]
        if roll <= upto:
            return item[:-1] if len(item) > 2 else item[0]
    return options[-1][:-1] if len(options[-1]) > 2 else options[-1][0]


def visitor_hash() -> bytes:
    return uuid.uuid4().bytes + uuid.uuid4().bytes[:16]


class Generator:
    def __init__(self, days: int, seed: int = 20260806):
        random.seed(seed)
        self.days = days
        self.rows: list[tuple] = []
        self.orders: list[dict] = []

    # -- catalog ---------------------------------------------------------- #

    def load_catalog(self, cur) -> None:
        cur.execute(
            """select p.id, p.slug::text as slug, p.name, p.category,
                      (select min(v.price_cents) from store.variants v
                        where v.product_id = p.id and v.archived_at is null) as min_price
                 from store.products p where p.archived_at is null and p.status = 'active'
                order by p.position"""
        )
        self.products = cur.fetchall()
        if not self.products:
            raise SystemExit("no active products -- run scripts.seed_catalog first")

        # A long tail on purpose: the top few take most of the attention, and
        # two products get views but never a sale, so "looked at, never bought"
        # has something real in it.
        n = len(self.products)
        self.view_weight = {}
        self.buy_weight = {}
        for i, p in enumerate(self.products):
            popularity = (n - i) ** 1.6
            self.view_weight[p["id"]] = popularity
            self.buy_weight[p["id"]] = popularity
        for p in self.products[-2:]:
            self.buy_weight[p["id"]] = 0.0          # viewed, never bought
        for p in self.products[max(0, n - 4):max(0, n - 2)]:
            self.view_weight[p["id"]] *= 0.15       # barely discovered

    def pick_product(self, weights) -> dict:
        pool = [p for p in self.products if weights[p["id"]] > 0]
        if not pool:
            return random.choice(self.products)
        return random.choices(pool, weights=[weights[p["id"]] for p in pool])[0]

    # -- events ----------------------------------------------------------- #

    def event(self, at, sid, vhash, name, path, device, browser, country, source,
              referrer, product_id=None, **props):
        props["demo"] = True
        self.rows.append((
            str(uuid.uuid4()), at, sid, vhash, name, path, product_id, None, None,
            device, browser, "windows" if device == "desktop" else "ios", country,
            referrer, json.dumps({"source": source} if source != "direct" else {}),
            json.dumps(props),
        ))

    def session(self, start: datetime) -> dict | None:
        sid = str(uuid.uuid4())
        vhash = visitor_hash()
        device = weighted(DEVICES)
        browser = weighted(BROWSERS)
        country = weighted(COUNTRIES)
        source, referrer = weighted(SOURCES)

        at = start
        landing = random.choices(["/", "/shop", "/about"], weights=[0.55, 0.35, 0.10])[0]

        # Roughly half of all arrivals bounce. That is normal, and a dashboard
        # that hides it is lying.
        bounced = random.random() < 0.44
        dwell = random.randint(3, 9) if bounced else random.randint(20, 90)
        clicks = 0 if bounced else random.randint(1, 4)
        scroll = random.randint(8, 30) if bounced else random.randint(35, 100)

        self.event(at, sid, vhash, "page_view", landing, device, browser, country, source, referrer,
                   page="home" if landing == "/" else landing.strip("/"))
        at += timedelta(seconds=dwell)
        self.event(at, sid, vhash, "page_exit", landing, device, browser, country, source, referrer,
                   active_seconds=dwell, scroll_pct=scroll, clicks=clicks, reason="unload")
        if bounced:
            return None

        # Some visitors search; a quarter of those find nothing.
        if random.random() < 0.28:
            at += timedelta(seconds=random.randint(2, 10))
            if random.random() < 0.25:
                term = random.choice(SEARCH_MISSES)
                self.event(at, sid, vhash, "search_zero_results", "/shop", device, browser,
                           country, source, referrer, term=term, results=0)
            else:
                term = random.choice(SEARCH_HITS)
                self.event(at, sid, vhash, "search", "/shop", device, browser, country, source,
                           referrer, term=term, results=random.randint(1, 6))

        viewed, carted, saved = [], [], []
        for _ in range(random.choices([1, 2, 3, 4], weights=[0.45, 0.3, 0.17, 0.08])[0]):
            product = self.pick_product(self.view_weight)
            path = f"/product/{product['slug']}"
            at += timedelta(seconds=random.randint(3, 20))

            self.event(at, sid, vhash, "product_click", "/shop", device, browser, country, source,
                       referrer, product_id=product["id"], slug=product["slug"],
                       position=random.randint(1, 12))
            self.event(at, sid, vhash, "product_view", path, device, browser, country, source,
                       referrer, product_id=product["id"], slug=product["slug"])
            viewed.append(product)

            pdwell = random.randint(12, 240)
            pclicks = random.randint(1, 8)
            for _ in range(random.randint(0, 3)):
                self.event(at, sid, vhash, "config_change", path, device, browser, country, source,
                           referrer, product_id=product["id"], slug=product["slug"],
                           field=random.choice(["frame", "size", "poster_theme"]),
                           value=random.choice(["walnut", "A3", "gold", "18x24", "circuit"]))

            if random.random() < 0.12:
                self.event(at, sid, vhash, "wishlist_add", path, device, browser, country, source,
                           referrer, product_id=product["id"], slug=product["slug"])
                saved.append(product)

            if random.random() < 0.24 and self.buy_weight[product["id"]] >= 0:
                self.event(at, sid, vhash, "add_to_cart", path, device, browser, country, source,
                           referrer, product_id=product["id"], slug=product["slug"],
                           frame=random.choice(["black", "walnut", "white", "gold"]),
                           size=random.choice(["A4", "A3", "12x18", "18x24"]),
                           qty=1, seconds_to_add=pdwell)
                carted.append(product)

            at += timedelta(seconds=pdwell)
            self.event(at, sid, vhash, "page_exit", path, device, browser, country, source,
                       referrer, product_id=product["id"], active_seconds=pdwell,
                       scroll_pct=random.randint(40, 100), clicks=pclicks, reason="unload")

        if not carted:
            return None

        at += timedelta(seconds=random.randint(5, 40))
        self.event(at, sid, vhash, "cart_view", "/cart", device, browser, country, source,
                   referrer, lines=len(carted))
        cdwell = random.randint(10, 70)
        at += timedelta(seconds=cdwell)
        self.event(at, sid, vhash, "page_exit", "/cart", device, browser, country, source,
                   referrer, active_seconds=cdwell, scroll_pct=random.randint(50, 100),
                   clicks=random.randint(1, 5), reason="unload")

        # Half of carts never reach checkout at all.
        if random.random() < 0.5:
            return None

        at += timedelta(seconds=random.randint(3, 20))
        self.event(at, sid, vhash, "checkout_start", "/checkout", device, browser, country,
                   source, referrer)
        fdwell = random.randint(30, 200)
        at += timedelta(seconds=fdwell)

        # Of those who start checkout, a third drop on the form -- and we record
        # which field they left blank, which is the actionable part.
        if random.random() < 0.34:
            self.event(at, sid, vhash, "checkout_field_blank", "/checkout", device, browser,
                       country, source, referrer,
                       field=random.choice(["zip", "state", "phone", "street"]))
            self.event(at, sid, vhash, "page_exit", "/checkout", device, browser, country,
                       source, referrer, active_seconds=fdwell, scroll_pct=60,
                       clicks=random.randint(2, 9), reason="unload")
            return None

        self.event(at, sid, vhash, "checkout_step", "/checkout", device, browser, country, source,
                   referrer, step="submit", seconds_on_form=fdwell)
        at += timedelta(seconds=2)
        self.event(at, sid, vhash, "purchase", "/checkout", device, browser, country, source,
                   referrer, seconds_to_purchase=fdwell)
        self.event(at, sid, vhash, "page_exit", "/checkout", device, browser, country, source,
                   referrer, active_seconds=fdwell + 10, scroll_pct=100,
                   clicks=random.randint(3, 10), reason="unload")

        buyable = [p for p in carted if self.buy_weight[p["id"]] > 0]
        if not buyable:
            return None
        return {"sid": sid, "at": at, "products": buyable, "country": country, "source": source}

    def run(self, cur) -> dict:
        self.load_catalog(cur)
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        sessions = 0

        for day_offset in range(self.days, 0, -1):
            day = now - timedelta(days=day_offset)
            base = 14 + day_offset * 0.35                 # gentle growth toward today
            count = int(base * DOW_WEIGHT[day.weekday()] * random.uniform(0.75, 1.3))
            for _ in range(count):
                hour = random.choices(range(24), weights=HOUR_WEIGHT)[0]
                start = day.replace(hour=hour) + timedelta(
                    minutes=random.randint(0, 59), seconds=random.randint(0, 59)
                )
                order = self.session(start)
                sessions += 1
                if order:
                    self.orders.append(order)
        return {"sessions": sessions, "events": len(self.rows), "orders": len(self.orders)}


EVENT_COLUMNS = ("event_id, occurred_at, session_id, visitor_hash, name, path, product_id, "
                 "variant_id, cart_id, device, browser, os, country, referrer_host, utm, props")


def write_events(cur, rows: list[tuple]) -> None:
    cur.execute("select raw.ensure_event_partitions(3)")
    # Older partitions may not exist for a long backfill; create what we need.
    cur.execute(
        """select distinct to_char(occurred_at, 'YYYYMM') as part
             from unnest(%s::timestamptz[]) occurred_at""",
        ([r[1] for r in rows],),
    )
    for row in cur.fetchall():
        part = f"events_{row['part']}"
        month = datetime.strptime(row["part"], "%Y%m").replace(tzinfo=timezone.utc)
        nxt = (month + timedelta(days=32)).replace(day=1)
        cur.execute(
            "select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'raw' and c.relname = %s", (part,)
        )
        if not cur.fetchone():
            cur.execute(
                f"create table raw.{part} partition of raw.events "
                f"for values from ('{month:%Y-%m-%d}') to ('{nxt:%Y-%m-%d}')"
            )
            cur.execute(f"grant insert, select on raw.{part} to ingest, etl")
            cur.execute(f"grant select on raw.{part} to admin_app")

    with cur.copy(f"copy raw.events ({EVENT_COLUMNS}) from stdin") as copy:
        for row in rows:
            copy.write_row(row)


def write_orders(cur, orders: list[dict]) -> int:
    """Demo orders, with the inventory ledger kept consistent.

    Stock is topped up first with an explicit 'receive' movement. Skipping that
    would drive components negative and trip stock_sane -- which is the
    constraint doing its job, and exactly why the generator must respect it
    rather than disable it.
    """
    if not orders:
        return 0
    needed = sum(len(o["products"]) for o in orders) * 2
    cur.execute(
        """insert into ops.inventory_ledger (component_id, delta, reason, note)
           select id, %s, 'receive', %s from ops.components""",
        (needed, f"{DEMO_MARK}: stock for generated orders"),
    )

    cur.execute("select key, add_cents from store.poster_themes")
    themes = {r["key"]: r["add_cents"] for r in cur.fetchall()}
    written = 0

    for order in orders:
        cur.execute(
            """insert into store.customers (email, name)
               values (%s, %s)
               on conflict (email) where archived_at is null do update set name = excluded.name
            returning id""",
            (f"demo-{order['sid'][:8]}@example.com", "Demo Buyer"),
        )
        customer_id = cur.fetchone()["id"]

        cur.execute(
            """insert into store.carts (session_id, state, converted_at, created_at, last_activity_at, email)
               values (%s, 'converted', %s, %s, %s, %s) returning id""",
            (order["sid"], order["at"], order["at"], order["at"],
             f"demo-{order['sid'][:8]}@example.com"),
        )
        cart_id = cur.fetchone()["id"]

        lines = []
        subtotal = 0
        for product in order["products"]:
            cur.execute(
                """select v.id, v.sku, v.price_cents, v.frame, v.size,
                          coalesce((select sum(c.unit_cost_cents * vc.qty)
                                      from ops.variant_components vc
                                      join ops.components c on c.id = vc.component_id
                                     where vc.variant_id = v.id), 0) as cost_cents
                     from store.variants v
                    where v.product_id = %s and v.archived_at is null
                    order by random() limit 1""",
                (product["id"],),
            )
            variant = cur.fetchone()
            theme = random.choice(list(themes))
            unit = variant["price_cents"] + themes[theme]
            qty = random.choices([1, 2], weights=[0.85, 0.15])[0]
            subtotal += unit * qty
            lines.append((variant, product, theme, unit, qty))

        total_qty = sum(line[4] for line in lines)
        discount = round(subtotal * 0.10) if total_qty >= 3 else 0

        cur.execute(
            """insert into store.orders
                 (customer_id, cart_id, email, payment_status, fulfilment_status,
                  subtotal_cents, discount_cents, total_cents, placed_at, paid_at,
                  ship_name, ship_street, ship_city, ship_state, ship_zip, ship_country,
                  internal_note)
               values (%s,%s,%s,'paid',%s,%s,%s,%s,%s,%s,'Demo Buyer','1 Example Way',
                       'Springfield','NY','10001',%s,%s)
            returning id""",
            (customer_id, cart_id, f"demo-{order['sid'][:8]}@example.com",
             random.choices(["fulfilled", "in_transit", "unfulfilled"], weights=[0.7, 0.2, 0.1])[0],
             subtotal, discount, subtotal - discount, order["at"], order["at"],
             order["country"], DEMO_MARK),
        )
        order_id = cur.fetchone()["id"]

        for variant, product, theme, unit, qty in lines:
            cur.execute(
                """insert into store.order_items
                     (order_id, variant_id, product_id, sku_snapshot, name_snapshot,
                      attrs_snapshot, qty, unit_price_cents, cost_cents, production_status)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'packed')""",
                (order_id, variant["id"], product["id"], variant["sku"], product["name"],
                 json.dumps({"frame": variant["frame"], "size": variant["size"],
                             "poster_theme": theme}),
                 qty, unit, variant["cost_cents"]),
            )
            cur.execute(
                """insert into ops.inventory_ledger (component_id, delta, reason, order_item_id, note)
                   select vc.component_id, -(vc.qty * %s), 'consume',
                          (select max(id) from store.order_items where order_id = %s), %s
                     from ops.variant_components vc where vc.variant_id = %s""",
                (qty, order_id, f"{DEMO_MARK}: generated order", variant["id"]),
            )
        written += 1
    return written


def purge(cur) -> dict:
    cur.execute("delete from raw.events where (props ->> 'demo')::boolean is true")
    events = cur.rowcount
    cur.execute("alter table store.order_items disable trigger t_freeze_order_items")
    cur.execute(
        """delete from ops.inventory_ledger
            where order_item_id in (select oi.id from store.order_items oi
                                      join store.orders o on o.id = oi.order_id
                                     where o.internal_note = %s)""",
        (DEMO_MARK,),
    )
    cur.execute("alter table ops.inventory_ledger disable trigger t_ledger_append_only")
    cur.execute("delete from ops.inventory_ledger where note like %s", (f"{DEMO_MARK}:%",))
    cur.execute("alter table ops.inventory_ledger enable trigger t_ledger_append_only")
    cur.execute(
        "delete from store.order_items where order_id in "
        "(select id from store.orders where internal_note = %s)", (DEMO_MARK,)
    )
    orders = cur.rowcount
    cur.execute("delete from store.orders where internal_note = %s", (DEMO_MARK,))
    cur.execute("alter table store.order_items enable trigger t_freeze_order_items")
    cur.execute("delete from store.cart_items where cart_id in "
                "(select id from store.carts where email like 'demo-%@example.com')")
    cur.execute("delete from store.carts where email like 'demo-%@example.com'")
    cur.execute("delete from store.customers where email like 'demo-%@example.com'")
    # Rebuild the cached balances from what is left, so drift stays zero.
    cur.execute(
        """update ops.components c
              set on_hand = coalesce(l.d, 0), reserved = coalesce(l.r, 0)
             from (select component_id, sum(delta) d, sum(reserved_delta) r
                     from ops.inventory_ledger group by component_id) l
            where l.component_id = c.id"""
    )
    return {"events": events, "order_items": orders}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--seed", type=int, default=20260806)
    parser.add_argument("--purge", action="store_true", help="remove all generated demo data")
    args = parser.parse_args()

    if os.environ.get("FO_ENV") == "production":
        raise SystemExit("refusing to generate demo traffic against production")

    with tx(Role.SUPER) as cur:
        if args.purge:
            print(purge(cur))
            return 0
        generator = Generator(args.days, args.seed)
        stats = generator.run(cur)
        write_events(cur, generator.rows)
        stats["orders_written"] = write_orders(cur, generator.orders)
        print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
