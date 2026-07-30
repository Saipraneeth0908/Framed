import json
import os
import re

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_change_me")

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "products.json")

# Frame categories that drive the theme switcher + poster filtering.
# Colors live in CSS (html[data-theme="<key>"]); this only owns label/tagline/order.
CATEGORIES = [
    {"key": "hotwheels", "label": "Hot Wheels", "tagline": "Die-cast icons, framed for the wall."},
    {"key": "cricket", "label": "Cricket", "tagline": "Legends of the pitch, in frame."},
    {"key": "anime", "label": "Anime", "tagline": "Frame your fandom."},
    {"key": "nature", "label": "Nature", "tagline": "The wild, on your wall."},
    {"key": "motivation", "label": "Motivation", "tagline": "Fuel for every single day."},
]

# Per-category homepage content. Each category is its own landing (/?cat=<key>):
# hero title/copy + "explore" collection cards + split-story, all category-specific.
# Images are pulled from that category's products at render time.
CATEGORY_CONTENT = {
    "all": {
        "eyebrow": "Every obsession, framed.",
        "title": ("Frame what you're", "obsessed", "with."),
        "subtitle": "Hot Wheels, cricket, anime, nature, motivation — pick a category up top to enter its world, then tune every frame before it reaches the wall.",
        "collections_eyebrow": "Find your line",
        "collections_title": "Explore by passion",
        "collections": [
            ("Hot Wheels", "Collector-grade die-cast."),
            ("Cricket & Anime", "Legends and heroes, framed."),
            ("Nature & Motivation", "Calm views and daily fuel."),
        ],
        "story": ("Any obsession.", "Made distinctly yours.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your piece", "Browse every collection in one place."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "hotwheels": {
        "eyebrow": "Die-cast icons, framed for the wall.",
        "title": ("Bring the", "starting grid", "to your walls."),
        "subtitle": "Collector-grade automotive art — racetracks, blueprints, and die-cast icons, framed with technical precision.",
        "collections_eyebrow": "Find your line",
        "collections_title": "Explore the garage",
        "collections": [
            ("Supercars", "Low, fast, and unmistakable."),
            ("Muscle", "Raw power in graphic form."),
            ("Track Icons", "Motorsport stories worth framing."),
        ],
        "story": ("One car.", "Made distinctly yours.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your icon", "Browse the Hot Wheels collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "cricket": {
        "eyebrow": "Legends of the pitch, in frame.",
        "title": ("Frame the", "pitch", "legends."),
        "subtitle": "Pitch geometry, seam detail, and match-day legends — framed with restrained, prestigious heritage.",
        "collections_eyebrow": "Find your side",
        "collections_title": "Explore the ground",
        "collections": [
            ("Batting Legends", "Icons at the crease."),
            ("Iconic Moments", "Match-day history, framed."),
            ("Team Colors", "Wear your side on the wall."),
        ],
        "story": ("One legend.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your legend", "Browse the Cricket collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "anime": {
        "eyebrow": "Frame your fandom.",
        "title": ("Frame your", "fandom", "in full energy."),
        "subtitle": "Manga panels, speed lines, and cinematic heroes — framed with expressive, immersive energy.",
        "collections_eyebrow": "Find your arc",
        "collections_title": "Explore the multiverse",
        "collections": [
            ("Shonen Heroes", "Protagonists in full power."),
            ("Villains & Arcs", "The dark side, framed."),
            ("Key Visuals", "Poster-grade cover art."),
        ],
        "story": ("One hero.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your hero", "Browse the Anime collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "nature": {
        "eyebrow": "The wild, on your wall.",
        "title": ("Frame the", "wild", "in calm."),
        "subtitle": "Topographic calm — landscapes, water, and light, framed as immersive, collectible art.",
        "collections_eyebrow": "Find your view",
        "collections_title": "Explore the wild",
        "collections": [
            ("Landscapes", "Mountains, water, and sky."),
            ("Seasons", "Color that shifts with time."),
            ("Stillness", "Calm you can hang."),
        ],
        "story": ("One landscape.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your view", "Browse the Nature collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "motivation": {
        "eyebrow": "Fuel for every single day.",
        "title": ("Frame your", "ambition", "with authority."),
        "subtitle": "Discipline, ambition, and progress — framed with generous space and monumental type.",
        "collections_eyebrow": "Find your drive",
        "collections_title": "Explore the mindset",
        "collections": [
            ("Discipline", "Show up. Every day."),
            ("Ambition", "Aim past the summit."),
            ("Focus", "Silence the noise."),
        ],
        "story": ("One mantra.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your mantra", "Browse the Motivation collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
}
CATEGORY_KEYS = {c["key"] for c in CATEGORIES}
# Fallback hero/story art for the "all" view (a car blueprint reads as the flagship).
DEFAULT_HERO_IMAGE = "/static/img/posters/mclaren-p1-blueprint.png"
DEFAULT_STORY_IMAGE = "/static/img/posters/mclaren-w1.png"

VALID_FRAMES = {"black", "walnut", "white", "gold"}
VALID_SIZES = {"A4", "A3", "12x18", "18x24"}
VALID_THEMES = {"racing_stripes", "circuit", "minimal"}
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
    return {"cart_count": cart_count, "categories": CATEGORIES}


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
    cat = request.args.get("cat", "all")
    if cat not in CATEGORY_KEYS:
        cat = "all"

    scope = products if cat == "all" else [p for p in products if p.get("category") == cat]
    featured = [p for p in scope if p.get("featured")] or scope
    label = next((c["label"] for c in CATEGORIES if c["key"] == cat), "All frames")

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


CHECKOUT_FIELDS = ("name", "email", "phone", "country", "street", "unit", "city", "state", "zip", "instructions", "default_addr")


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_init()
    totals = compute_cart_totals(session["cart"])
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
        if not session["cart"]:
            return back("Your cart is empty. Add a poster before checking out.")

        # Stripe later: for now, simulate order submit. A real app would persist
        # this structured address on the order and create a PaymentIntent.
        session["cart"] = []
        session.modified = True
        return render_template("checkout.html", success=True, shipped_to=data, page_title="Checkout | Framed Obsessions")

    return render_template(
        "checkout.html", totals=totals, form_data={}, states=US_STATES, countries=COUNTRIES,
        page_title="Checkout | Framed Obsessions",
    )


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
