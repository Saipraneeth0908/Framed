"""Storefront routes.

Reads the catalog from Postgres as store_app. Carts and orders are server-side
(store.carts / store.orders); the cookie holds a token, never prices.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for

from common import csrf
from common.http import harden_session, init_health, init_request_id, init_security_headers, require_secret
from db.conn import Role, tx
from web import carts as cart_repo
from web.catalog import degraded, get_product_by_slug, load_categories, load_products, static_asset_exists
from web.content import CATEGORY_CONTENT, CATEGORY_KEYS, DEFAULT_HERO_IMAGE, DEFAULT_STORY_IMAGE
from web.pricing import (
    VALID_FRAMES,
    VALID_SIZES,
    VALID_THEMES,
    compute_cart_totals,
    compute_config_price,
    normalize_config,
    parse_quantity,
)

ROOT = Path(__file__).resolve().parent.parent

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
app.secret_key = require_secret("FLASK_SECRET_KEY")

harden_session(app, cookie_name="fo_web")
init_request_id(app)
init_security_headers(
    app,
    csp=(
        "default-src 'self'; "
        "script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; "      # inline width: on the bundle progress bar
        "img-src 'self' data: blob:; "            # blob: is the wall-preview upload
        f"connect-src 'self' {os.environ.get('COLLECTOR_ORIGIN', '')}; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://checkout.stripe.com"
    ),
)
# api_price is JSON-only with no cookie-authed side effect; the Stripe webhook
# is authenticated by HMAC signature instead, which is strictly stronger.
csrf.init_app(app, exempt_endpoints={"api_price", "stripe_webhook", "healthz", "readyz"})

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

COUNTRIES = ["United States", "Canada", "United Kingdom", "Australia", "India", "Germany", "France", "Other"]
US_STATES = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"), ("CA", "California"),
    ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"), ("DC", "District of Columbia"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"), ("IL", "Illinois"),
    ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"),
    ("ME", "Maine"), ("MD", "Maryland"), ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"),
    ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"), ("OR", "Oregon"),
    ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"), ("SD", "South Dakota"),
    ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"),
    ("WA", "Washington"), ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"),
]

CHECKOUT_FIELDS = ("name", "email", "phone", "country", "street", "unit", "city", "state", "zip",
                   "instructions", "default_addr")


# --------------------------------------------------------------------------- #
# Cart plumbing. The session holds only the cart token; quantities and prices
# live in store.cart_items where the customer cannot edit them.
# --------------------------------------------------------------------------- #

def cart_items():
    token = session.get("cart_token")
    return cart_repo.items(token) if token else []


def cart_init():
    if not session.get("cart_token"):
        session["cart_token"] = cart_repo.create(session_id=session.get("analytics_sid"))
    return session["cart_token"]


@app.context_processor
def inject_site_context():
    count = sum(parse_quantity(i.get("qty", 0), default=0) for i in getattr(g, "_cart_items", cart_items()))
    return {"cart_count": count, "categories": load_categories()}


@app.before_request
def _load_cart_once():
    g._cart_items = cart_items()


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

@app.route("/")
def home():
    products = load_products()
    cat = request.args.get("cat", "all")
    if cat not in CATEGORY_KEYS:
        cat = "all"

    scope = products if cat == "all" else [p for p in products if p.get("category") == cat]
    featured = [p for p in scope if p.get("featured")] or scope
    label = next((c["label"] for c in load_categories() if c["key"] == cat), "All frames")

    # Hero + split-story artwork: prefer this category's own posters.
    hero_product = featured[0] if featured else None
    if cat == "all":
        hero_image, story_image = DEFAULT_HERO_IMAGE, DEFAULT_STORY_IMAGE
    else:
        hero_image = hero_product["images"]["poster"] if hero_product else DEFAULT_HERO_IMAGE
        story_image = (scope[-1] if scope else hero_product)["images"]["poster"] if scope else DEFAULT_STORY_IMAGE

    content = CATEGORY_CONTENT[cat]
    # "All Frames" hero gets a scrolling frame-wall background (built client-side from these).
    marquee_images = (
        [p["images"]["poster"] for p in products if p.get("images", {}).get("poster_available")]
        if cat == "all"
        else []
    )
    return render_template(
        "home.html",
        content=content,
        featured=featured,
        hero_product=hero_product,
        hero_image=hero_image,
        story_image=story_image,
        marquee_images=marquee_images,
        active_category=cat,
        active_label=label,
        design_count=len(scope),
        newsletter_status=request.args.get("newsletter"),
        page_title=f"{label} | Framed Obsessions" if cat != "all" else "Framed Obsessions | Framed posters",
        page_description=content["subtitle"],
    )


@app.route("/shop")
def shop():
    products = load_products()
    return render_template(
        "shop.html",
        products=products,
        page_title="Shop Automotive Posters | Framed Obsessions",
        page_description="Browse customizable framed automotive posters by brand, color, style, and price.",
    )


@app.route("/product/<slug>")
def product(slug):
    products = load_products()
    p = get_product_by_slug(products, slug)
    if not p:
        return redirect(url_for("shop"))

    # Shareable config via query params (Wishlist share links)
    config = normalize_config(
        request.args.get("frame", "black"),
        request.args.get("size", "A3"),
        request.args.get("poster_theme", "racing_stripes"),
    )

    unit_price = compute_config_price(p["base_price"], config["frame"], config["size"], config["poster_theme"])
    related = [
        item
        for item in products
        if item["slug"] != p["slug"]
        and (item["brand"] == p["brand"] or set(item.get("tags", [])) & set(p.get("tags", [])))
    ][:3]
    return render_template(
        "product.html",
        product=p,
        config=config,
        unit_price=unit_price,
        related=related,
        page_title=f"{p['name']} | Framed Obsessions",
        page_description=p["short_desc"],
    )


@app.route("/api/price", methods=["POST"])
def api_price():
    data = request.get_json(silent=True) or {}
    products = load_products()
    p = get_product_by_slug(products, str(data.get("slug", "")))
    if not p:
        return jsonify({"error": "Product not found."}), 404
    config = normalize_config(data.get("frame"), data.get("size"), data.get("poster_theme"))
    price = compute_config_price(p["base_price"], **config)
    return jsonify({"price": price})


@app.route("/cart")
def cart():
    products = load_products()

    hydrated = []
    for item in cart_items():
        p = get_product_by_slug(products, item["slug"])
        if not p:
            continue
        hydrated.append(
            {
                **item,
                "product": {
                    "name": p["name"],
                    "brand": p["brand"],
                    "slug": p["slug"],
                    "thumb": p.get("images", {}).get("poster", ""),
                },
            }
        )

    totals = compute_cart_totals(hydrated)
    return render_template("cart.html", cart_items=hydrated, totals=totals)


@app.route("/cart/add", methods=["POST"])
def cart_add():
    slug = request.form.get("slug", "").strip()
    qty = parse_quantity(request.form.get("qty", "1"))
    config = normalize_config(
        request.form.get("frame", "black"),
        request.form.get("size", "A3"),
        request.form.get("poster_theme", "racing_stripes"),
    )

    products = load_products()
    p = get_product_by_slug(products, slug)
    if not p:
        return redirect(url_for("shop"))
    if qty <= 0:
        return redirect(url_for("product", slug=slug))

    token = cart_init()
    # Price is recomputed server-side from the catalog; the posted form cannot
    # influence it.
    unit_cents = round(compute_config_price(p["base_price"], **config) * 100)
    cart_repo.add(token, slug, config, qty, unit_cents)
    return redirect(url_for("cart"))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    try:
        idx = int(request.form.get("idx", "-1"))
    except (TypeError, ValueError):
        idx = -1
    qty = parse_quantity(request.form.get("qty", "1"))
    token = session.get("cart_token")
    if token:
        cart_repo.update_by_index(token, idx, qty)
    return redirect(url_for("cart"))


@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    token = session.get("cart_token")
    if token:
        cart_repo.clear(token)
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items = cart_items()
    totals = compute_cart_totals(items)
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in CHECKOUT_FIELDS}
        required = ("name", "email", "street", "city", "state", "zip")

        def back(message):
            return render_template(
                "checkout.html", error=message, form_data=data, totals=totals,
                states=US_STATES, countries=COUNTRIES, page_title="Checkout | Framed Obsessions",
            )

        if any(not data[k] for k in required):
            return back("Please fill in all required fields.")
        if not EMAIL_PATTERN.match(data["email"]):
            return back("Enter a valid email address.")
        if not items:
            return back("Your cart is empty. Add a poster before checking out.")

        from web.orders import OutOfStock, place_order

        try:
            order = place_order(session["cart_token"], data, items)
        except OutOfStock as exc:
            return back(str(exc))

        session.pop("cart_token", None)
        if order.get("checkout_url"):
            return redirect(order["checkout_url"])     # Stripe Checkout takes over
        return render_template(
            "checkout.html", success=True, shipped_to=data, order=order,
            page_title="Checkout | Framed Obsessions",
        )

    return render_template(
        "checkout.html", totals=totals, form_data={}, states=US_STATES, countries=COUNTRIES,
        page_title="Checkout | Framed Obsessions",
    )


@app.route("/webhooks/stripe", methods=["POST"], endpoint="stripe_webhook")
def stripe_webhook():
    """Stripe is the system of record for money; this is how it tells us.

    Idempotent on the Stripe event id, because Stripe retries on any non-2xx and
    a double-delivery must not reserve stock twice.
    """
    from web.orders import OutOfStock, mark_paid
    from web.payments import StripeGateway, gateway

    gw = gateway()
    if not isinstance(gw, StripeGateway):
        abort(404)
    try:
        event = gw.verify_webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
    except ValueError as exc:
        log.warning("rejected Stripe webhook: %s", exc)
        abort(400)

    with tx(Role.STORE) as cur:
        cur.execute(
            "insert into raw.outbox (topic, payload) values (%s, %s) on conflict do nothing",
            (f"stripe.{event['type']}", json.dumps(event)),
        )

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        try:
            mark_paid(int(obj["client_reference_id"]), payment_ref=obj.get("payment_intent"))
        except OutOfStock:
            # Money took, stock gone: this needs a human, not a retry loop.
            log.error("oversell after payment on order %s", obj.get("client_reference_id"))
    return "", 204


@app.route("/newsletter", methods=["POST"])
def newsletter():
    email = request.form.get("email", "").strip()
    status = "success" if EMAIL_PATTERN.match(email) else "error"
    return redirect(url_for("home", newsletter=status) + "#updates")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        # No email integration now; just show success
        return render_template("contact.html", success=True)
    return render_template("contact.html")


def _ready():
    with tx(Role.STORE) as cur:
        cur.execute("select 1 as ok")
        cur.fetchone()
    return {"ready": True, "catalog": "fallback" if degraded() else "postgres"}


init_health(app, ready_check=_ready)

__all__ = [
    "app", "load_products", "get_product_by_slug", "static_asset_exists",
    "compute_config_price", "compute_cart_totals", "normalize_config", "parse_quantity",
    "VALID_FRAMES", "VALID_SIZES", "VALID_THEMES", "US_STATES", "COUNTRIES",
]
