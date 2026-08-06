"""Payment gateway adapter.

Two implementations behind one method. Which one runs is decided by whether
STRIPE_SECRET_KEY is set, so the whole checkout path -- including the oversell
rejection -- is runnable end to end locally without Stripe credentials.

No stripe SDK: two REST calls and an HMAC do not justify the dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

STRIPE_API = "https://api.stripe.com/v1"


class StubGateway:
    """Marks the order paid inline. Development and CI only."""

    name = "stub"

    def charge(self, order_id: int, amount_cents: int, email: str) -> dict:
        from web.orders import mark_paid

        mark_paid(order_id, payment_ref=f"stub_{order_id}")
        return {"paid": True, "gateway": self.name}


class StripeGateway:
    name = "stripe"

    def __init__(self, secret: str, success_url: str, cancel_url: str, webhook_secret: str = ""):
        self.secret = secret
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.webhook_secret = webhook_secret

    def _post(self, path: str, form: list[tuple[str, str]]) -> dict:
        req = urllib.request.Request(
            f"{STRIPE_API}{path}",
            data=urllib.parse.urlencode(form).encode(),
            headers={
                "Authorization": f"Bearer {self.secret}",
                "Content-Type": "application/x-www-form-urlencoded",
                # Stripe dedupes on this key, so a retried checkout submit
                # cannot create a second session for the same order.
                "Idempotency-Key": form[0][1] if form else "",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def charge(self, order_id: int, amount_cents: int, email: str) -> dict:
        session = self._post(
            "/checkout/sessions",
            [
                ("client_reference_id", str(order_id)),
                ("mode", "payment"),
                ("customer_email", email),
                ("success_url", self.success_url),
                ("cancel_url", self.cancel_url),
                ("line_items[0][quantity]", "1"),
                ("line_items[0][price_data][currency]", "usd"),
                ("line_items[0][price_data][unit_amount]", str(amount_cents)),
                ("line_items[0][price_data][product_data][name]", "Framed Obsessions order"),
            ],
        )
        return {"paid": False, "gateway": self.name, "checkout_url": session["url"]}

    def verify_webhook(self, payload: bytes, sig_header: str, tolerance: int = 300) -> dict:
        """Constant-time signature check with replay window, per Stripe's spec."""
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        timestamp, signature = parts.get("t", ""), parts.get("v1", "")
        if not timestamp or not signature:
            raise ValueError("malformed Stripe-Signature header")
        if abs(time.time() - int(timestamp)) > tolerance:
            raise ValueError("webhook timestamp outside tolerance")
        expected = hmac.new(
            self.webhook_secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("webhook signature mismatch")
        return json.loads(payload)


_gateway = None


def gateway():
    global _gateway
    if _gateway is None:
        secret = os.environ.get("STRIPE_SECRET_KEY")
        if secret:
            base = os.environ.get("STORE_BASE_URL", "http://localhost:8000")
            _gateway = StripeGateway(
                secret,
                success_url=f"{base}/checkout?paid=1",
                cancel_url=f"{base}/cart",
                webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
            )
        else:
            log.warning("STRIPE_SECRET_KEY unset -- using the stub gateway, orders settle instantly")
            _gateway = StubGateway()
    return _gateway
