"""Catalog reads.

``products()`` returns the exact dict shape the old ``load_products()`` produced
from data/products.json, including the derived ``*_available`` keys, so every
template and JS file keeps working untouched. That equivalence is asserted by
tests/test_catalog_parity.py -- the regression gate for the riskiest step of the
whole migration.
"""

from __future__ import annotations

from db.conn import Role, tx

# One round trip. Aggregating in SQL beats 4 queries x 11 products, and the
# json_agg filters keep empty lists as [] rather than [null].
_PRODUCTS_SQL = """
select
  p.legacy_id                                        as id,
  p.slug::text                                       as slug,
  p.name, p.brand, p.series, p.category, p.color,
  coalesce(t.tags, '[]'::json)                       as tags,
  p.base_price_cents,
  p.featured,
  p.short_desc,
  p.description,
  p.status::text                                     as status,
  p.position,
  p.specs,
  coalesce(i.poster, '')                             as poster,
  coalesce(i.gallery,   '[]'::json)                  as gallery,
  coalesce(i.frames360, '[]'::json)                  as frames360,
  coalesce(i.customer_photos, '[]'::json)            as customer_photos,
  coalesce(r.reviews, '[]'::json)                    as reviews
from store.products p
left join lateral (
  select json_agg(pt.tag::text order by pt.position, pt.tag) as tags
    from store.product_tags pt where pt.product_id = p.id
) t on true
left join lateral (
  select
    max(pi.url) filter (where pi.role = 'poster')                          as poster,
    json_agg(pi.url order by pi.position) filter (where pi.role = 'gallery')        as gallery,
    json_agg(pi.url order by pi.position) filter (where pi.role = 'frame360')       as frames360,
    json_agg(pi.url order by pi.position) filter (where pi.role = 'customer_photo') as customer_photos
    from store.product_images pi where pi.product_id = p.id
) i on true
left join lateral (
  select json_agg(json_build_object('name', pr.name, 'rating', pr.rating, 'text', pr.body)
                  order by pr.created_at) as reviews
    from store.product_reviews pr where pr.product_id = p.id and pr.approved
) r on true
where p.archived_at is null and p.status = 'active'
order by p.position, p.id
"""


def _to_legacy(row: dict) -> dict:
    """Postgres row -> the dict shape data/products.json used to hand back."""
    return {
        "id": row["id"],
        "slug": row["slug"],
        "name": row["name"],
        "brand": row["brand"],
        "series": row["series"],
        "category": row["category"],
        "color": row["color"],
        "tags": row["tags"] or [],
        # Whole-dollar prices were ints in the JSON and reach the DOM as
        # data-price / "From $89". Returning 89.0 would render "$89.0" -- a
        # visible change from a migration that is supposed to change nothing.
        "base_price": (
            row["base_price_cents"] // 100
            if row["base_price_cents"] % 100 == 0
            else row["base_price_cents"] / 100
        ),
        "featured": row["featured"],
        "short_desc": row["short_desc"],
        "images": {
            "poster": row["poster"],
            "gallery": row["gallery"] or [],
            "frames360": row["frames360"] or [],
        },
        "specs": row["specs"] or {},
        "reviews": row["reviews"] or [],
        "customer_photos": row["customer_photos"] or [],
    }


def products(role: str = Role.STORE) -> list[dict]:
    with tx(role) as cur:
        cur.execute(_PRODUCTS_SQL)
        return [_to_legacy(r) for r in cur.fetchall()]


def categories(role: str = Role.STORE) -> list[dict]:
    with tx(role) as cur:
        cur.execute(
            """select key, label, tagline, content from store.categories
                where archived_at is null order by position, key"""
        )
        return cur.fetchall()


def poster_themes(role: str = Role.STORE) -> list[dict]:
    with tx(role) as cur:
        cur.execute(
            """select key, label, add_cents from store.poster_themes
                where archived_at is null order by position, key"""
        )
        return cur.fetchall()


def variant_for(slug: str, frame: str, size: str, role: str = Role.STORE) -> dict | None:
    """The variant a (slug, frame, size) configuration resolves to."""
    with tx(role) as cur:
        cur.execute(
            """select v.id, v.sku, v.price_cents, v.sale_price_cents, v.status,
                      p.id as product_id, p.name, p.slug::text as slug
                 from store.variants v
                 join store.products p on p.id = v.product_id
                where p.slug = %s and v.frame = %s and v.size = %s
                  and v.archived_at is null and p.archived_at is null""",
            (slug, frame, size),
        )
        return cur.fetchone()


def variant_cost_cents(variant_id: int, role: str = Role.STORE) -> int:
    """Summed bill of materials -- frozen onto the order line for real margin."""
    with tx(role) as cur:
        cur.execute(
            """select coalesce(sum(c.unit_cost_cents * vc.qty), 0)::bigint as cost
                 from ops.variant_components vc
                 join ops.components c on c.id = vc.component_id
                where vc.variant_id = %s""",
            (variant_id,),
        )
        row = cur.fetchone()
        return int(row["cost"]) if row else 0
