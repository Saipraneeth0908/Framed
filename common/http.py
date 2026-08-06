"""Request identity, security headers and health endpoints.

One request_id is minted per request and threaded into logs, the audit trigger
and the response header, so a single id traces web -> collector -> worker.
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid

from flask import Flask, g, jsonify, request

log = logging.getLogger(__name__)


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes", "on"}


def require_secret(var: str) -> str:
    """Fail fast at import time rather than shipping a guessable default key.

    A hardcoded fallback secret means every deploy that forgets the env var
    silently accepts forged session cookies. Refusing to boot is the correct
    failure mode.
    """
    value = os.environ.get(var)
    if value:
        return value
    if _truthy("FO_ALLOW_INSECURE_SECRET"):
        log.warning("%s unset; using an ephemeral key (FO_ALLOW_INSECURE_SECRET is on)", var)
        return secrets.token_urlsafe(48)
    raise RuntimeError(
        f"{var} is not set. Generate one with `python -c \"import secrets;print(secrets.token_urlsafe(48))\"` "
        f"or set FO_ALLOW_INSECURE_SECRET=1 for local development."
    )


def harden_session(app: Flask, *, cookie_name: str, cookie_domain: str | None = None,
                   lifetime_seconds: int = 60 * 60 * 12) -> None:
    app.config.update(
        SESSION_COOKIE_NAME=cookie_name,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Secure defaults on; local http development sets FO_INSECURE_COOKIES=1.
        SESSION_COOKIE_SECURE=not _truthy("FO_INSECURE_COOKIES"),
        SESSION_COOKIE_DOMAIN=cookie_domain or None,
        PERMANENT_SESSION_LIFETIME=lifetime_seconds,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )


def init_request_id(app: Flask) -> None:
    @app.before_request
    def _mint():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

    @app.after_request
    def _echo(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return response


def init_security_headers(app: Flask, *, csp: str, frame_ancestors_none: bool = True) -> None:
    @app.before_request
    def _nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def _headers(response):
        response.headers["Content-Security-Policy"] = csp.replace("{nonce}", getattr(g, "csp_nonce", ""))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if frame_ancestors_none:
            response.headers["X-Frame-Options"] = "DENY"
        if not _truthy("FO_INSECURE_COOKIES"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app.jinja_env.globals["csp_nonce"] = lambda: getattr(g, "csp_nonce", "")


def init_health(app: Flask, *, ready_check=None) -> None:
    """/healthz: is the process alive. /readyz: can it serve.

    Split on purpose so an orchestrator restarts the right thing -- a process
    that is alive but cannot reach Postgres should be pulled from the load
    balancer, not killed.
    """

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok"), 200

    @app.get("/readyz")
    def readyz():
        if ready_check is None:
            return jsonify(status="ready"), 200
        try:
            detail = ready_check()
        except Exception as exc:                       # noqa: BLE001
            log.exception("readiness check failed")
            return jsonify(status="degraded", error=str(exc)), 503
        code = 200 if detail.get("ready") else 503
        return jsonify(detail), code
