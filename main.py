from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json
import os

app = Flask(__name__)
app.secret_key = "dev_secret_change_me"

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "products.json")


def load_products():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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


def compute_config_price(base_price, frame, size, poster_theme):
    # frame pricing
    frame_add = {
        "black": 0,
        "walnut": 15,
        "white": 10,
        "gold": 20
    }.get(frame, 0)

    # size pricing
    size_add = {
        "A4": 0,
        "A3": 12,
        "12x18": 18,
        "18x24": 28
    }.get(size, 0)

    # poster theme pricing
    theme_add = {
        "racing_stripes": 0,
        "circuit": 8,
        "minimal": 0
    }.get(poster_theme, 0)

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

    return {
        "subtotal": round(subtotal, 2),
        "bundle_discount": bundle_discount,
        "total": total,
        "total_qty": total_qty
    }


@app.route("/")
def home():
    products = load_products()
    featured = [p for p in products if p.get("featured")]
    return render_template("home.html", featured=featured, products=products[:12])


@app.route("/shop")
def shop():
    products = load_products()
    return render_template("shop.html", products=products)


@app.route("/product/<slug>")
def product(slug):
    products = load_products()
    p = get_product_by_slug(products, slug)
    if not p:
        return redirect(url_for("shop"))

    # Shareable config via query params (Wishlist share links)
    config = {
        "frame": request.args.get("frame", "black"),
        "size": request.args.get("size", "A3"),
        "poster_theme": request.args.get("poster_theme", "racing_stripes"),
    }

    unit_price = compute_config_price(p["base_price"], config["frame"], config["size"], config["poster_theme"])
    return render_template("product.html", product=p, config=config, unit_price=unit_price)


@app.route("/api/price", methods=["POST"])
def api_price():
    data = request.get_json(force=True)
    base_price = data.get("base_price", 0)
    frame = data.get("frame", "black")
    size = data.get("size", "A3")
    poster_theme = data.get("poster_theme", "racing_stripes")
    price = compute_config_price(base_price, frame, size, poster_theme)
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
        hydrated.append({
            **item,
            "product": {
                "name": p["name"],
                "brand": p["brand"],
                "slug": p["slug"],
                "thumb": p.get("images", {}).get("poster", "")
            }
        })

    totals = compute_cart_totals(hydrated)
    return render_template("cart.html", cart_items=hydrated, totals=totals)


@app.route("/cart/add", methods=["POST"])
def cart_add():
    cart_init()
    products = load_products()

    slug = request.form.get("slug", "").strip()
    qty = int(request.form.get("qty", "1"))
    frame = request.form.get("frame", "black")
    size = request.form.get("size", "A3")
    poster_theme = request.form.get("poster_theme", "racing_stripes")

    p = get_product_by_slug(products, slug)
    if not p:
        return redirect(url_for("shop"))

    unit_price = compute_config_price(p["base_price"], frame, size, poster_theme)

    # If same slug+config exists, increment
    found = False
    for item in session["cart"]:
        if item["slug"] == slug and item.get("config", {}) == {"frame": frame, "size": size, "poster_theme": poster_theme}:
            item["qty"] = int(item.get("qty", 1)) + qty
            found = True
            break

    if not found:
        session["cart"].append({
            "slug": slug,
            "qty": qty,
            "config": {"frame": frame, "size": size, "poster_theme": poster_theme},
            "unit_price": unit_price
        })

    session.modified = True
    return redirect(url_for("cart"))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    cart_init()
    idx = int(request.form.get("idx", "-1"))
    qty = int(request.form.get("qty", "1"))
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
            return render_template("checkout.html", error="Please fill all required fields.")

        # In a real app you would create an order + payment intent
        session["cart"] = []
        session.modified = True
        return render_template("checkout.html", success=True)

    # GET
    totals = compute_cart_totals(session["cart"])
    return render_template("checkout.html", totals=totals)


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
