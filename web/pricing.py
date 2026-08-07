"""Configuration validation and price arithmetic.

Prices are computed in cents and converted at the boundary. Floats drift; the
old float base_price is the bug this fixes. The public helpers keep returning
dollars-as-float because every template and the /api/price contract expect that.
"""

from __future__ import annotations

VALID_FRAMES = {"black", "walnut", "white", "gold"}
VALID_SIZES = {"A4", "A3", "12x18", "18x24"}
VALID_THEMES = {"racing_stripes", "circuit", "minimal"}

FRAME_ADD_CENTS = {"black": 0, "walnut": 1500, "white": 1000, "gold": 2000}
SIZE_ADD_CENTS = {"A4": 0, "A3": 1200, "12x18": 1800, "18x24": 2800}
THEME_ADD_CENTS = {"racing_stripes": 0, "circuit": 800, "minimal": 0}

BUNDLE_MIN_QTY = 3
BUNDLE_PERCENT = 10


def normalize_config(frame, size, poster_theme):
    return {
        "frame": frame if frame in VALID_FRAMES else "black",
        "size": size if size in VALID_SIZES else "A3",
        "poster_theme": poster_theme if poster_theme in VALID_THEMES else "racing_stripes",
    }


def parse_quantity(value, default=1, maximum=25):
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(quantity, maximum))


def config_price_cents(base_price_cents: int, frame: str, size: str, poster_theme: str) -> int:
    return (
        int(base_price_cents)
        + FRAME_ADD_CENTS.get(frame, 0)
        + SIZE_ADD_CENTS.get(size, 0)
        + THEME_ADD_CENTS.get(poster_theme, 0)
    )


def compute_config_price(base_price, frame, size, poster_theme):
    """Dollars in, dollars out -- the signature every caller already uses."""
    cents = config_price_cents(round(float(base_price) * 100), frame, size, poster_theme)
    return round(cents / 100, 2)


def compute_cart_totals(cart_items):
    """
    cart_items: list of dict line items:
      {slug, qty, config: {frame,size,poster_theme}, unit_price}
    Applies the Build-a-Set discount: total poster qty >= 3 => 10% off posters.
    """
    subtotal_cents = 0
    total_qty = 0

    for item in cart_items:
        qty = int(item.get("qty", 1))
        subtotal_cents += qty * round(float(item.get("unit_price", 0)) * 100)
        total_qty += qty

    discount_cents = 0
    if total_qty >= BUNDLE_MIN_QTY:
        discount_cents = round(subtotal_cents * BUNDLE_PERCENT / 100)

    return {
        "subtotal": round(subtotal_cents / 100, 2),
        "bundle_discount": round(discount_cents / 100, 2),
        "total": round((subtotal_cents - discount_cents) / 100, 2),
        "total_qty": total_qty,
    }
