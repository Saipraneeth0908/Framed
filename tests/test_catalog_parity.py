"""The regression gate for the riskiest step of the migration.

load_products() must return from Postgres exactly what it used to return from
data/products.json -- same keys, same order, same types. Every template and JS
file depends on that shape, and "89" vs "89.0" is a visible price change.
"""

from __future__ import annotations

import json
from pathlib import Path

from web.catalog import _decorate, load_products

ROOT = Path(__file__).resolve().parent.parent


def _from_json():
    return _decorate(json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8")))


def test_postgres_catalog_matches_the_json_it_replaced():
    assert load_products() == _from_json()


def test_price_types_survive_the_round_trip():
    for product in load_products():
        price = product["base_price"]
        assert isinstance(price, int) or price != int(price), (
            f"{product['slug']} base_price {price!r} would render as '$89.0'"
        )


def test_tag_order_is_authored_not_alphabetical():
    by_slug = {p["slug"]: p["tags"] for p in load_products()}
    expected = {p["slug"]: p["tags"] for p in _from_json()}
    assert by_slug == expected


def test_derived_availability_keys_are_present():
    for product in load_products():
        assert "poster_available" in product["images"]
        assert "available_gallery" in product["images"]
        assert "available_frames" in product["images"]
        assert "available_customer_photos" in product
