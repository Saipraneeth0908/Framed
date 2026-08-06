"""Admin application factory.

Separate process, separate hostname, separate cookie, separate secret, separate
database role. Nothing here is reachable from the storefront process.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, render_template

from admin import auth, views
from admin.rbac import Perm, has, permissions_for
from admin.sessions import RedisSessionInterface
from common import csrf
from common.http import (
    harden_session,
    init_health,
    init_metrics,
    init_request_id,
    init_security_headers,
    require_secret,
)
from db.conn import Role, tx

HERE = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(HERE / "templates"),
        static_folder=str(HERE / "static"),
        static_url_path="/assets",
    )
    app.secret_key = require_secret("ADMIN_SECRET_KEY")

    # Distinct cookie name AND distinct domain: a stolen storefront cookie is
    # meaningless here, and vice versa.
    harden_session(app, cookie_name="fo_adm", cookie_domain=os.environ.get("ADMIN_COOKIE_DOMAIN"))
    app.session_interface = RedisSessionInterface()

    init_request_id(app)
    # Only the Metabase origin may be framed, and only if one is configured.
    frame_src = os.environ.get("METABASE_SITE_URL") or "'none'"
    init_security_headers(
        app,
        csp=(
            "default-src 'self'; "
            "script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            f"frame-src {frame_src}; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        ),
    )
    csrf.init_app(app, exempt_endpoints={"healthz", "readyz"})

    @app.before_request
    def _authenticate():
        auth.attach_user()
        return auth.login_required_guard()

    app.jinja_env.globals.update(
        Perm=Perm,
        can=has,
        money=_money,
        permissions_for=permissions_for,
    )
    app.jinja_env.filters["money"] = _money
    app.jinja_env.filters["ago"] = _ago

    app.register_blueprint(auth.bp)
    for blueprint in views.ALL:
        app.register_blueprint(blueprint)

    @app.errorhandler(403)
    def _forbidden(exc):
        return render_template("error.html", code=403, title="Not your permission level",
                               detail="Your role does not include this action.",
                               page_title="Forbidden"), 403

    @app.errorhandler(404)
    def _missing(exc):
        return render_template("error.html", code=404, title="Nothing here",
                               detail="That record does not exist.", page_title="Not found"), 404

    @app.errorhandler(409)
    def _conflict(exc):
        return render_template("error.html", code=409, title="Illegal transition",
                               detail=getattr(exc, "description", "That change is not allowed from the current state."),
                               page_title="Conflict"), 409

    init_health(app, ready_check=_ready)
    init_metrics(app, service="admin")
    return app


def _money(cents, symbol: str = "$") -> str:
    if cents is None:
        return "—"
    return f"{symbol}{int(cents) / 100:,.2f}"


def _ago(value) -> str:
    from datetime import datetime, timezone

    if value is None:
        return "—"
    seconds = int((datetime.now(timezone.utc) - value).total_seconds())
    if seconds < 90:
        return "just now"
    for limit, size, label in ((3600, 60, "min"), (86400, 3600, "hr"), (604800, 86400, "day")):
        if seconds < limit:
            unit = seconds // size
            return f"{unit} {label}{'s' if unit != 1 else ''} ago"
    return value.strftime("%d %b %Y")


def _ready():
    with tx(Role.ADMIN) as cur:
        cur.execute("select 1")
    return {"ready": True, "role": "admin_app"}


app = create_app()
