"""Per-session CSRF tokens.

Flask-WTF would be a dependency for one 40-line feature and drags WTForms in
with it. This is the whole contract: a random token in the session, echoed in
every mutating form, compared in constant time.
"""

from __future__ import annotations

import hmac
import secrets

from flask import abort, g, request, session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
FIELD = "_csrf"
HEADER = "X-CSRF-Token"


def token() -> str:
    if FIELD not in session:
        session[FIELD] = secrets.token_urlsafe(32)
    return session[FIELD]


def validate() -> None:
    if request.method in SAFE_METHODS or getattr(g, "csrf_exempt", False):
        return
    sent = request.form.get(FIELD) or request.headers.get(HEADER, "")
    expected = session.get(FIELD, "")
    if not expected or not sent or not hmac.compare_digest(sent, expected):
        abort(400, description="CSRF token missing or invalid.")


def init_app(app, *, exempt_endpoints: set[str] | None = None) -> None:
    exempt = exempt_endpoints or set()

    @app.before_request
    def _check():
        if request.endpoint in exempt:
            g.csrf_exempt = True
        validate()

    app.jinja_env.globals["csrf_token"] = token
