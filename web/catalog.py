"""Catalog reads for the storefront.

Postgres is authoritative. data/products.json stays as a read-only fallback for
one release (per the migration plan) so a database blip degrades the storefront
to a stale catalog instead of a 500 -- selling keeps working, which is the
availability property that actually matters.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from db.repo import catalog as repo
from web.content import CATEGORIES

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
JSON_FALLBACK = ROOT / "data" / "products.json"

# Set when a DB read fails, so /readyz can report degraded without a second probe.
_degraded = False


def degraded() -> bool:
    return _degraded


def static_asset_exists(url_path: str | None) -> bool:
    if not url_path or not url_path.startswith("/static/"):
        return False
    relative_path = url_path.removeprefix("/static/").replace("/", os.sep)
    return os.path.isfile(os.path.join(STATIC_DIR, relative_path))


def _decorate(products: list[dict]) -> list[dict]:
    """Attach the derived availability keys the templates read."""
    for product in products:
        images = product.get("images", {})
        images["poster_available"] = static_asset_exists(images.get("poster"))
        images["available_gallery"] = [p for p in images.get("gallery", []) if static_asset_exists(p)]
        images["available_frames"] = [p for p in images.get("frames360", []) if static_asset_exists(p)]
        product["available_customer_photos"] = [
            p for p in product.get("customer_photos", []) if static_asset_exists(p)
        ]
    return products


def _from_json() -> list[dict]:
    with open(JSON_FALLBACK, "r", encoding="utf-8") as f:
        return json.load(f)


def load_products() -> list[dict]:
    """Same return shape as the original JSON loader. Asserted by test_catalog_parity."""
    global _degraded
    try:
        products = repo.products()
        _degraded = False
    except Exception:                                 # noqa: BLE001 - any DB failure
        log.exception("catalog read failed, serving data/products.json fallback")
        _degraded = True
        products = _from_json()
    return _decorate(products)


def load_categories() -> list[dict]:
    try:
        rows = repo.categories()
        return [{"key": r["key"], "label": r["label"], "tagline": r["tagline"]} for r in rows]
    except Exception:                                 # noqa: BLE001
        log.exception("category read failed, using web.content.CATEGORIES")
        return CATEGORIES


def get_product_by_slug(products, slug):
    for p in products:
        if p["slug"] == slug:
            return p
    return None
