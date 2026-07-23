import json
import os
import re

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_change_me")

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "products.json")
VALID_FRAMES = {"black", "walnut", "white", "gold"}
VALID_SIZES = {"A4", "A3", "12x18", "18x24"}
VALID_THEMES = {"racing_stripes", "circuit", "minimal"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def load_products():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        products = json.load(f)
    for product in products:
        images = product.get("images", {})
        images["poster_available"] = static_asset_exists(images.get("poster"))
        images["available_gallery"] = [path for path in images.get("gallery", []) if static_asset_exists(path)]
        images["available_frames"] = [path for path in images.get("frames360", []) if static_asset_exists(path)]
        product["available_customer_photos"] = [
            path for path in product.get("customer_photos", []) if static_asset_exists(path)
        ]
    return products


def static_asset_exists(url_path):
    if not url_path or not url_path.startswith("/static/"):
        return False
    relative_path = url_path.removeprefix("/static/").replace("/", os.sep)
    return os.path.isfile(os.path.join(app.static_folder, relative_path))


def get_product_by_slug(products, slug):
    for p in products:
        if p["slug"] == slug:
            return p
    return None


def cart_init():
    if "cart" not in session:
        session["cart"] = []  # list of line items


def wishlist_init():
    if "wishlist" not in session:
        session["wishlist"] = []  # list of saved design ids


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


@app.context_processor
def inject_site_context():
    cart_items = session.get("cart", [])
    cart_count = sum(parse_quantity(item.get("qty", 0), default=0) for item in cart_items)
    return {"cart_count": cart_count}


def compute_config_price(base_price, frame, size, poster_theme):
    # frame pricing
    frame_add = {"black": 0, "walnut": 15, "white": 10, "gold": 20}.get(frame, 0)

    # size pricing
    size_add = {"A4": 0, "A3": 12, "12x18": 18, "18x24": 28}.get(size, 0)

    # poster theme pricing
    theme_add = {"racing_stripes": 0, "circuit": 8, "minimal": 0}.get(poster_theme, 0)

    return round(float(base_price) + frame_add + size_add + theme_add, 2)


def compute_cart_totals(cart_items):
    """
    cart_items: list of dict line items:
      {
        slug, qty,
        config: {frame,size,poster_theme},
        unit_price
      }
    Applies:
      - Build-a-Set discount: if total poster qty >= 3 => 10% off posters
      - Frame bundle toggle (optional later): keep simple now
    """
    subtotal = 0.0
    total_qty = 0

    for item in cart_items:
        qty = int(item.get("qty", 1))
        unit_price = float(item.get("unit_price", 0))
        subtotal += qty * unit_price
        total_qty += qty

    bundle_discount = 0.0
    if total_qty >= 3:
        bundle_discount = round(subtotal * 0.10, 2)

    total = round(subtotal - bundle_discount, 2)

    return {"subtotal": round(subtotal, 2), "bundle_discount": bundle_discount, "total": total, "total_qty": total_qty}


@app.route("/")
def home():
    products = load_products()
    featured = [p for p in products if p.get("featured")]
    themes = {
        "Performance": [
            p for p in products if any(tag in p.get("tags", []) for tag in ("supercar", "hypercar", "sport"))
        ],
        "Track Icons": [p for p in products if any(tag in p.get("tags", []) for tag in ("race", "classic", "icon"))],
        "Muscle": [p for p in products if "muscle" in p.get("tags", [])],
    }
    return render_template(
        "home.html",
        featured=featured,
        products=products[:12],
        themes=themes,
        newsletter_status=request.args.get("newsletter"),
        page_title="Motorsport Gallery | Framed automotive art",
        page_description=(
            "Discover customizable framed automotive posters, build a gallery set, and preview artwork on your wall."
        ),
    )


@app.route("/shop")
def shop():
    products = load_products()
    return render_template(
        "shop.html",
        products=products,
        page_title="Shop Automotive Posters | Motorsport Gallery",
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
        page_title=f"{p['name']} | Motorsport Gallery",
        page_description=p["short_desc"],
    )


@app.route("/api/price", methods=["POST"])
def api_price():
    data = request.get_json(silent=True) or {}
    products = load_products()
    product = get_product_by_slug(products, str(data.get("slug", "")))
    if not product:
        return jsonify({"error": "Product not found."}), 404
    config = normalize_config(data.get("frame"), data.get("size"), data.get("poster_theme"))
    price = compute_config_price(product["base_price"], **config)
    return jsonify({"price": price})


@app.route("/cart")
def cart():
    cart_init()
    products = load_products()

    # hydrate line items with product info
    hydrated = []
    for item in session["cart"]:
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
    cart_init()
    products = load_products()

    slug = request.form.get("slug", "").strip()
    qty = parse_quantity(request.form.get("qty", "1"))
    config = normalize_config(
        request.form.get("frame", "black"),
        request.form.get("size", "A3"),
        request.form.get("poster_theme", "racing_stripes"),
    )
    frame, size, poster_theme = config["frame"], config["size"], config["poster_theme"]

    p = get_product_by_slug(products, slug)
    if not p:
        return redirect(url_for("shop"))
    if qty <= 0:
        return redirect(url_for("product", slug=slug))

    unit_price = compute_config_price(p["base_price"], frame, size, poster_theme)

    # If same slug+config exists, increment
    found = False
    for item in session["cart"]:
        if item["slug"] == slug and item.get("config", {}) == {
            "frame": frame,
            "size": size,
            "poster_theme": poster_theme,
        }:
            item["qty"] = int(item.get("qty", 1)) + qty
            found = True
            break

    if not found:
        session["cart"].append(
            {
                "slug": slug,
                "qty": qty,
                "config": {"frame": frame, "size": size, "poster_theme": poster_theme},
                "unit_price": unit_price,
            }
        )

    session.modified = True
    return redirect(url_for("cart"))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    cart_init()
    try:
        idx = int(request.form.get("idx", "-1"))
    except (TypeError, ValueError):
        idx = -1
    qty = parse_quantity(request.form.get("qty", "1"))
    if 0 <= idx < len(session["cart"]):
        if qty <= 0:
            session["cart"].pop(idx)
        else:
            session["cart"][idx]["qty"] = qty
        session.modified = True
    return redirect(url_for("cart"))


@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    session["cart"] = []
    session.modified = True
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_init()
    if request.method == "POST":
        # Stripe later: for now, simulate order submit
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()

        if not name or not email or not address:
            return render_template("checkout.html", error="Please fill all required fields.", form_data=request.form)
        if not EMAIL_PATTERN.match(email):
            return render_template("checkout.html", error="Enter a valid email address.", form_data=request.form)
        if not session["cart"]:
            return render_template("checkout.html", error="Your cart is empty.", form_data=request.form)

        # In a real app you would create an order + payment intent
        session["cart"] = []
        session.modified = True
        return render_template("checkout.html", success=True)

    # GET
    totals = compute_cart_totals(session["cart"])
    return render_template("checkout.html", totals=totals, page_title="Checkout | Motorsport Gallery")


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


if __name__ == "__main__":
    app.run(debug=True)
