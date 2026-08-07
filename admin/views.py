"""Admin routes.

Every view carries exactly one @require(Perm.…) or @public. There is no
implicit default: tests/test_admin_rbac.py fails the build if a route appears
without one, which is how "deny by default" stays true as routes are added.
"""

from __future__ import annotations

import csv
import io
import json
import logging

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from admin.rbac import Perm, require
from db.repo import admin as repo
from db.repo import analytics as analytics_repo

log = logging.getLogger(__name__)

dashboard = Blueprint("dashboard", __name__)
orders = Blueprint("orders", __name__, url_prefix="/orders")
production = Blueprint("production", __name__, url_prefix="/production")
inventory = Blueprint("inventory", __name__, url_prefix="/inventory")
catalog = Blueprint("catalog", __name__, url_prefix="/catalog")
people = Blueprint("people", __name__, url_prefix="/people")
growth = Blueprint("growth", __name__, url_prefix="/growth")
insights = Blueprint("insights", __name__, url_prefix="/insights")
system = Blueprint("system", __name__, url_prefix="/system")

ALL = [dashboard, orders, production, inventory, catalog, people, growth, insights, system]


def _actor() -> int:
    return g.user["id"]


def _int(name: str, default: int = 0) -> int:
    try:
        return int(request.form.get(name, request.args.get(name, default)))
    except (TypeError, ValueError):
        return default


def _cents(name: str) -> int:
    """Money arrives as dollars from a form and is stored as cents, always."""
    raw = (request.form.get(name) or "0").replace(",", "").replace("$", "").strip()
    try:
        return round(float(raw) * 100)
    except ValueError:
        return 0


# --------------------------------------------------------------------------- #
# Action board
# --------------------------------------------------------------------------- #

@dashboard.get("/")
@require(Perm.ORDER_VIEW)
def index():
    settings = repo.settings()
    stuck_hours = int(settings.get("ops.stuck_order_hours", 24))
    return render_template(
        "dashboard.html",
        board=repo.action_board(stuck_hours),
        kpis=repo.kpis(),
        spark=repo.revenue_sparkline(30),
        recent=repo.orders(limit=8),
        stuck_hours=stuck_hours,
        page_title="Action board",
    )


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #

@orders.get("/")
@require(Perm.ORDER_VIEW)
def list_orders():
    status = request.args.get("status", "")
    query = request.args.get("q", "").strip()
    page = max(_int("page", 1), 1)
    rows = repo.orders(status=status, query=query, limit=50, offset=(page - 1) * 50)
    return render_template("orders.html", orders=rows, status=status, q=query, page=page,
                           page_title="Orders")


@orders.get("/<int:order_id>")
@require(Perm.ORDER_VIEW)
def order_detail(order_id: int):
    order = repo.order(order_id)
    if not order:
        abort(404)
    return render_template("order_detail.html", order=order,
                           page_title=f"Order {order['order_no']}")


@orders.post("/<int:order_id>/fulfilment")
@require(Perm.ORDER_EDIT)
def set_fulfilment(order_id: int):
    repo.set_fulfilment(order_id, request.form.get("status", "unfulfilled"), _actor())
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders.post("/<int:order_id>/ship")
@require(Perm.ORDER_EDIT)
def ship(order_id: int):
    repo.add_shipment(
        order_id,
        request.form.get("carrier", "").strip(),
        request.form.get("tracking_no", "").strip(),
        request.form.get("tracking_url", "").strip(),
        _actor(),
    )
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders.post("/<int:order_id>/cancel")
@require(Perm.ORDER_CANCEL)
def cancel(order_id: int):
    from web.orders import restock_for_item

    reason = request.form.get("reason", "").strip() or "cancelled by staff"
    order = repo.order(order_id)
    if not order:
        abort(404)
    repo.cancel_order(order_id, reason, _actor())
    if request.form.get("restock") == "on":
        for item in order["items"]:
            restock_for_item(item["id"], "cancel_restock", actor_id=_actor())
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders.post("/<int:order_id>/refund")
@require(Perm.ORDER_REFUND)
def refund(order_id: int):
    from web.orders import restock_for_item

    item_id = _int("order_item_id") or None
    qty = _int("qty") or None
    amount = _cents("amount")
    if amount <= 0:
        abort(400, description="Refund amount must be positive.")
    restock = request.form.get("restock") == "on"
    repo.refund(order_id, item_id, amount, qty, request.form.get("reason", "").strip() or "refund",
                restock, _actor())
    if restock and item_id:
        restock_for_item(item_id, "return", actor_id=_actor())
    return redirect(url_for("orders.order_detail", order_id=order_id))


@orders.get("/<int:order_id>/packing-slip")
@require(Perm.ORDER_VIEW)
def packing_slip(order_id: int):
    order = repo.order(order_id)
    if not order:
        abort(404)
    return render_template("packing_slip.html", order=order,
                           page_title=f"Packing slip {order['order_no']}")


# --------------------------------------------------------------------------- #
# Production board -- button-advance so it works one-handed in the workshop.
# --------------------------------------------------------------------------- #

@production.get("/")
@require(Perm.PRODUCTION_VIEW)
def board():
    return render_template("production.html", board=repo.production_board(),
                           stations=repo.STATION_ORDER, next_station=repo.NEXT_STATION,
                           page_title="Production")


@production.post("/<int:item_id>/advance")
@require(Perm.PRODUCTION_EDIT)
def advance(item_id: int):
    to_status = request.form.get("to", "")
    try:
        repo.advance_item(item_id, to_status, _actor(), request.form.get("reason", ""))
    except KeyError:
        abort(404)
    except ValueError as exc:
        abort(409, description=str(exc))
    return redirect(request.form.get("next") or url_for("production.board"))


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #

@inventory.get("/")
@require(Perm.STOCK_VIEW)
def components():
    return render_template(
        "inventory.html",
        components=repo.components(request.args.get("kind", ""), request.args.get("low") == "1"),
        kind=request.args.get("kind", ""),
        low=request.args.get("low") == "1",
        page_title="Inventory",
    )


@inventory.get("/<int:component_id>")
@require(Perm.STOCK_VIEW)
def component_detail(component_id: int):
    component = repo.component(component_id)
    if not component:
        abort(404)
    return render_template("component.html", component=component, page_title=component["sku"])


@inventory.post("/<int:component_id>/adjust")
@require(Perm.STOCK_EDIT)
def adjust(component_id: int):
    delta = _int("delta")
    if delta == 0:
        abort(400, description="An adjustment of zero changes nothing.")
    repo.adjust_stock(component_id, delta, request.form.get("reason", "receive"),
                      request.form.get("note", ""), _actor())
    return redirect(url_for("inventory.component_detail", component_id=component_id))


@inventory.get("/reorder")
@require(Perm.STOCK_VIEW)
def reorder():
    return render_template("reorder.html", rows=repo.reorder_list(), page_title="Reorder list")


@inventory.get("/reorder.csv")
@require(Perm.STOCK_VIEW)
def reorder_csv():
    return _csv_response(repo.reorder_list(), "reorder-list.csv")


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

@catalog.get("/")
@require(Perm.PRODUCT_VIEW)
def products():
    return render_template(
        "catalog.html",
        products=repo.products(request.args.get("q", "").strip(), request.args.get("category", "")),
        q=request.args.get("q", ""),
        category=request.args.get("category", ""),
        page_title="Catalog",
    )


@catalog.get("/<int:product_id>")
@require(Perm.PRODUCT_VIEW)
def product_detail(product_id: int):
    product = repo.product(product_id)
    if not product:
        abort(404)
    return render_template("product_detail.html", product=product, page_title=product["name"])


@catalog.post("/<int:product_id>")
@require(Perm.PRODUCT_EDIT)
def update_product(product_id: int):
    repo.update_product(product_id, {
        "name": request.form.get("name", "").strip(),
        "brand": request.form.get("brand", "").strip() or None,
        "category": request.form.get("category", "").strip(),
        "short_desc": request.form.get("short_desc", "").strip() or None,
        "description": request.form.get("description", "").strip() or None,
        "status": request.form.get("status", "draft"),
        "featured": request.form.get("featured") == "on",
        "position": _int("position"),
    }, _actor())
    return redirect(url_for("catalog.product_detail", product_id=product_id))


@catalog.post("/variant/<int:variant_id>")
@require(Perm.PRICE_EDIT)
def update_variant(variant_id: int):
    sale = _cents("sale_price") or None
    repo.update_variant(variant_id, _cents("price"), sale, request.form.get("status", "active"),
                        _actor())
    return redirect(request.form.get("next") or url_for("catalog.products"))


@catalog.post("/<int:product_id>/archive")
@require(Perm.ARCHIVE)
def archive_product(product_id: int):
    repo.archive_product(product_id, _actor())
    return redirect(url_for("catalog.products"))


@catalog.get("/export.csv")
@require(Perm.PRODUCT_VIEW)
def export_csv():
    return _csv_response(repo.products(include_archived=True), "catalog.csv")


@catalog.get("/variants.csv")
@require(Perm.PRODUCT_VIEW)
def export_variants_csv():
    """The round-trip file: export, edit prices in a spreadsheet, import back."""
    return _csv_response(repo.variants_for_export(), "variants.csv")


@catalog.get("/import")
@require(Perm.PRICE_EDIT)
def import_form():
    return render_template("import.html", result=None, page_title="Bulk price import")


@catalog.post("/import")
@require(Perm.PRICE_EDIT)
def import_csv():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        abort(400, description="Choose a CSV file first.")

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        abort(400, description="That file is not UTF-8. Re-export it as CSV UTF-8.")

    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        row = {"sku": (record.get("sku") or "").strip()}
        for source, target in (("price_cents", "price_cents"), ("sale_price_cents", "sale_price_cents")):
            raw = (record.get(source) or "").strip()
            if raw == "":
                continue
            try:
                row[target] = int(raw)
            except ValueError:
                # A spreadsheet will happily hand back "116.00" for a cents
                # column; accept it rather than rejecting the whole file.
                try:
                    row[target] = round(float(raw))
                except ValueError:
                    row[target] = None
        if (record.get("status") or "").strip():
            row["status"] = record["status"].strip()
        rows.append(row)

    if len(rows) > 5000:
        abort(400, description="That is more than 5000 rows; split the file.")

    result = repo.bulk_update_variants(rows, _actor())
    result["submitted"] = len(rows)
    log.info("bulk import by uid=%s: %s", _actor(), result)
    return render_template("import.html", result=result, page_title="Bulk price import")


@catalog.post("/bulk")
@require(Perm.PRODUCT_EDIT)
def bulk_products():
    ids = [int(v) for v in request.form.getlist("product_id") if v.isdigit()]
    changed = repo.bulk_update_products(
        ids,
        {"status": request.form.get("status"),
         "category": request.form.get("category"),
         "featured": True if request.form.get("featured") == "on" else None},
        _actor(),
    )
    log.info("bulk product edit by uid=%s touched %d rows", _actor(), changed)
    return redirect(url_for("catalog.products"))


# --------------------------------------------------------------------------- #
# People
# --------------------------------------------------------------------------- #

@people.get("/customers")
@require(Perm.CUSTOMER_VIEW)
def customers():
    return render_template("customers.html", customers=repo.customers(request.args.get("q", "")),
                           q=request.args.get("q", ""), page_title="Customers")


@people.get("/customers.csv")
@require(Perm.CUSTOMER_EXPORT)
def customers_csv():
    # Gated behind its own permission: this file is the entire PII set.
    log.warning("customer export by uid=%s", _actor())
    return _csv_response(repo.customers(limit=100000), "customers.csv")


@people.get("/users")
@require(Perm.USER_MANAGE)
def users():
    return render_template("users.html", users=repo.users(), page_title="Staff")


@people.post("/users")
@require(Perm.USER_MANAGE)
def create_user():
    from admin.auth import create_user as make

    password = request.form.get("password", "")
    if len(password) < 12:
        abort(400, description="Use at least 12 characters.")
    make(request.form.get("email", "").strip().lower(), request.form.get("name", "").strip(),
         password, request.form.get("role", "fulfilment"), actor_id=_actor())
    return redirect(url_for("people.users"))


@people.post("/users/<int:user_id>/role")
@require(Perm.USER_MANAGE)
def change_role(user_id: int):
    from admin.auth import set_role

    set_role(user_id, request.form.get("role", "fulfilment"), actor_id=_actor())
    return redirect(url_for("people.users"))


@people.post("/users/<int:user_id>/reset-2fa")
@require(Perm.USER_MANAGE)
def reset_two_factor(user_id: int):
    """Lost phone, or a rotated ADMIN_TOTP_KEY that orphaned every secret.

    Without this the only screen that can re-enrol somebody sits behind the
    login they can no longer complete, and the fix is a shell on the database.
    """
    from admin.auth import reset_totp

    log.warning("2fa reset for uid=%s by uid=%s", user_id, _actor())
    reset_totp(user_id, actor_id=_actor())
    return redirect(url_for("people.users"))


# --------------------------------------------------------------------------- #
# Growth
# --------------------------------------------------------------------------- #

@growth.get("/discounts")
@require(Perm.DISCOUNT_EDIT)
def discounts():
    return render_template("discounts.html", discounts=repo.discounts(), page_title="Discounts")


@growth.post("/discounts")
@require(Perm.DISCOUNT_EDIT)
def create_discount():
    kind = request.form.get("kind", "percent")
    value = _int("value") if kind == "percent" else _cents("value")
    repo.create_discount(request.form.get("code", "").strip(), kind, value,
                         _cents("min_subtotal"), _int("max_redemptions") or None, _actor())
    return redirect(url_for("growth.discounts"))


# --------------------------------------------------------------------------- #
# Insights -- Metabase does the analytics; this page frames it.
# --------------------------------------------------------------------------- #

def _window() -> int:
    """Shared date window. One control, in one place, for every chart on a page."""
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    return days if days in (7, 30, 90, 365) else 30


def _analytics_context(days: int) -> dict:
    """Shared footer context for every insights page.

    Called last in each render_template(...) call on purpose: keyword arguments
    evaluate in source order, so by the time this runs every panel's query has
    already run and take_failures() can report the ones that broke.
    """
    ready = analytics_repo.marts_ready()
    ingestion = analytics_repo.events_today()
    return {
        "days": days,
        "marts": ready,
        "marts_missing": [name for name, ok in ready.items() if not ok],
        "ingestion": ingestion,
        "query_errors": analytics_repo.take_failures(),
    }


@insights.get("/")
@require(Perm.ANALYTICS_VIEW)
def analytics():
    days = _window()
    return render_template(
        "insights_overview.html",
        headline=analytics_repo.headline(days),
        trend=analytics_repo.sessions_by_day(days),
        funnel=analytics_repo.funnel(days),
        outcomes=analytics_repo.outcomes(days),
        depth=analytics_repo.depth_bands(days),
        devices=analytics_repo.device_split(days),
        page_title="Insights",
        **_analytics_context(days),
    )


@insights.get("/behaviour")
@require(Perm.ANALYTICS_VIEW)
def behaviour():
    days = _window()
    return render_template(
        "insights_behaviour.html",
        pages=analytics_repo.page_engagement(20),
        clicks=analytics_repo.click_targets(18),
        heat=analytics_repo.hourly_heatmap(),
        devices=analytics_repo.device_split(days),
        depth=analytics_repo.depth_bands(days),
        page_title="Behaviour",
        **_analytics_context(days),
    )


@insights.get("/products")
@require(Perm.ANALYTICS_VIEW)
def products_analytics():
    days = _window()
    sort = request.args.get("sort", "views")
    return render_template(
        "insights_products.html",
        journey=analytics_repo.product_journey(sort, 30),
        best=analytics_repo.sellers("best", 8),
        worst=analytics_repo.sellers("worst", 8),
        never_bought=analytics_repo.looked_never_bought(12),
        sort=sort,
        page_title="Product performance",
        **_analytics_context(days),
    )


@insights.get("/abandonment")
@require(Perm.ANALYTICS_VIEW)
def abandonment():
    days = _window()
    return render_template(
        "insights_abandonment.html",
        live=analytics_repo.live_carts(25),
        totals=analytics_repo.live_totals(),
        abandoned=analytics_repo.abandoned_interest(15),
        outcomes=analytics_repo.outcomes(days),
        page_title="Abandonment",
        **_analytics_context(days),
    )


@insights.get("/acquisition")
@require(Perm.ANALYTICS_VIEW)
def acquisition():
    days = _window()
    return render_template(
        "insights_acquisition.html",
        sources=analytics_repo.acquisition(days),
        landings=analytics_repo.landing_pages(10),
        searches=analytics_repo.search_demand(15),
        lost=analytics_repo.lost_demand(15),
        trend=analytics_repo.sessions_by_day(days),
        page_title="Acquisition",
        **_analytics_context(days),
    )


@insights.get("/embed")
@require(Perm.ANALYTICS_VIEW)
def embedded_dashboards():
    """Metabase, for questions this panel does not answer.

    Optional by design: the dashboards above are first-party and always work.
    """
    from admin.embeds import dashboards, embed_url, embedding_configured

    return render_template(
        "insights_embed.html",
        configured=embedding_configured(),
        dashboards=[(d, embed_url(d)) for d in dashboards()],
        page_title="Metabase",
        **_analytics_context(_window()),
    )


# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #

@system.get("/settings")
@require(Perm.SETTINGS_VIEW)
def settings():
    return render_template("settings.html", settings=repo.settings(), page_title="Settings")


@system.post("/settings")
@require(Perm.SETTINGS_EDIT)
def update_settings():
    for key, raw in request.form.items():
        if key.startswith("_") or not key.startswith(("store.", "ops.")):
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        repo.set_setting(key, value, _actor())
    return redirect(url_for("system.settings"))


@system.get("/audit")
@require(Perm.AUDIT_VIEW)
def audit():
    return render_template("audit.html", entries=repo.audit_log(request.args.get("entity", "")),
                           entity=request.args.get("entity", ""), page_title="Audit log")


def _csv_response(rows: list[dict], filename: str) -> Response:
    if not rows:
        return Response("", mimetype="text/csv")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
