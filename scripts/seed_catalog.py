"""Seed store.products / variants / BOM from data/products.json.

Idempotent: re-running upserts and leaves prices untouched. The variant prices
are derived from the *existing* compute_config_price() adders, so nothing the
customer sees moves during the cutover -- tests/test_catalog_parity.py asserts
exactly that.

    python -m scripts.seed_catalog
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.conn import Role, tx  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "products.json"

# Frozen copies of the storefront's pricing ladder. Duplicated on purpose: this
# script must reproduce the prices as they were on the day of the cutover, even
# if web/pricing.py changes tomorrow.
FRAME_ADD = {"black": 0, "walnut": 15, "white": 10, "gold": 20}
SIZE_ADD = {"A4": 0, "A3": 12, "12x18": 18, "18x24": 28}
ORDER_FRAMES = ["black", "walnut", "white", "gold"]
ORDER_SIZES = ["A4", "A3", "12x18", "18x24"]


def size_key(size: str) -> str:
    return size.replace("x", "X").upper()


def sku_for(legacy_id: str, frame: str, size: str) -> str:
    return f"{legacy_id.upper()}-{frame[:3].upper()}-{size_key(size)}"


def seed() -> dict:
    products = json.loads(DATA.read_text(encoding="utf-8"))
    counts = {"products": 0, "variants": 0, "images": 0, "tags": 0, "reviews": 0, "bom": 0}

    with tx(Role.SUPER) as cur:
        cur.execute("select id, sku from ops.components")
        components = {r["sku"]: r["id"] for r in cur.fetchall()}
        if not components:
            raise SystemExit("ops.components is empty -- run migrations first (dbmate up)")

        for position, p in enumerate(products, start=1):
            base_cents = round(float(p["base_price"]) * 100)
            cur.execute(
                """
                insert into store.products
                  (legacy_id, slug, name, brand, series, category, color, short_desc,
                   base_price_cents, status, featured, position, specs)
                values (%(legacy_id)s, %(slug)s, %(name)s, %(brand)s, %(series)s, %(category)s,
                        %(color)s, %(short_desc)s, %(base_cents)s, 'active', %(featured)s,
                        %(position)s, %(specs)s)
                on conflict (slug) where archived_at is null do update set
                  legacy_id = excluded.legacy_id, name = excluded.name, brand = excluded.brand,
                  series = excluded.series, category = excluded.category, color = excluded.color,
                  short_desc = excluded.short_desc, base_price_cents = excluded.base_price_cents,
                  featured = excluded.featured, position = excluded.position, specs = excluded.specs
                returning id
                """,
                {
                    "legacy_id": p["id"], "slug": p["slug"], "name": p["name"], "brand": p.get("brand"),
                    "series": p.get("series"), "category": p["category"], "color": p.get("color"),
                    "short_desc": p.get("short_desc"), "base_cents": base_cents,
                    "featured": bool(p.get("featured")), "position": position,
                    "specs": json.dumps(p.get("specs", {})),
                },
            )
            product_id = cur.fetchone()["id"]
            counts["products"] += 1

            # Child rows are replaced wholesale: the JSON file is the source
            # until the cutover completes, so a delete+insert is both simpler
            # and more correct than diffing.
            cur.execute("delete from store.product_images where product_id = %s", (product_id,))
            rows = [("poster", p["images"]["poster"], 0)]
            rows += [("gallery", u, i) for i, u in enumerate(p["images"].get("gallery", []))]
            rows += [("frame360", u, i) for i, u in enumerate(p["images"].get("frames360", []))]
            rows += [("customer_photo", u, i) for i, u in enumerate(p.get("customer_photos", []))]
            for role, url, pos in rows:
                if not url:
                    continue
                cur.execute(
                    "insert into store.product_images (product_id, role, url, position) values (%s,%s,%s,%s)",
                    (product_id, role, url, pos),
                )
                counts["images"] += 1

            cur.execute("delete from store.product_tags where product_id = %s", (product_id,))
            for tpos, tag in enumerate(p.get("tags", [])):
                cur.execute(
                    """insert into store.product_tags (product_id, tag, position) values (%s,%s,%s)
                       on conflict (product_id, tag) do update set position = excluded.position""",
                    (product_id, tag, tpos),
                )
                counts["tags"] += 1

            cur.execute("delete from store.product_reviews where product_id = %s", (product_id,))
            for rv in p.get("reviews", []):
                cur.execute(
                    "insert into store.product_reviews (product_id, name, rating, body) values (%s,%s,%s,%s)",
                    (product_id, rv["name"], rv["rating"], rv["text"]),
                )
                counts["reviews"] += 1

            # 16 variants: 4 frames x 4 sizes. Poster theme is a line-item
            # option (store.poster_themes), not a variant axis.
            vpos = 0
            for frame in ORDER_FRAMES:
                for size in ORDER_SIZES:
                    price = base_cents + FRAME_ADD[frame] * 100 + SIZE_ADD[size] * 100
                    cur.execute(
                        """
                        insert into store.variants
                          (product_id, sku, frame, size, orientation, price_cents, status, position)
                        values (%s, %s, %s, %s, 'portrait', %s, 'active', %s)
                        on conflict (product_id, frame, size, orientation, coalesce(finish, ''))
                        do update set price_cents = excluded.price_cents, sku = excluded.sku,
                                      position = excluded.position
                        returning id
                        """,
                        (product_id, sku_for(p["id"], frame, size), frame, size, price, vpos),
                    )
                    variant_id = cur.fetchone()["id"]
                    counts["variants"] += 1
                    vpos += 1

                    sk = size_key(size)
                    bom = [
                        f"FRM-{sk}-{frame[:3].upper()}",
                        f"PPR-{sk}",
                        f"MNT-{sk}",
                        f"GLS-{sk}",
                        f"PKG-{sk}",
                    ]
                    for csku in bom:
                        cid = components.get(csku)
                        if cid is None:
                            raise SystemExit(f"missing component {csku} -- migration 008 out of sync")
                        cur.execute(
                            """insert into ops.variant_components (variant_id, component_id, qty)
                               values (%s,%s,1) on conflict (variant_id, component_id) do nothing""",
                            (variant_id, cid),
                        )
                        counts["bom"] += 1
    return counts


if __name__ == "__main__":
    os.environ.setdefault("DB_POOL_MAX", "2")
    print(seed())
