"""Event collector.

    browser (sendBeacon) -> POST /e -> validate -> XADD to a Redis Stream -> 204

The Redis Stream is the durability boundary: Postgres can be down for
maintenance and no events are lost. Nothing here touches Postgres, and nothing
here blocks a storefront request -- the storefront only knows a URL.

Privacy: the raw IP exists only inside this request. It is used to derive a
country and a rotating salted visitor hash, then discarded. It is never
persisted and never logged. Because no cookie is set for analytics, no consent
banner is legally required.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone

import redis
from flask import Flask, request

from common.http import init_health, init_request_id

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

STREAM = "fo:events"
MAX_BODY = 64 * 1024
MAX_BATCH = 50
STREAM_MAXLEN = 500_000          # bounded so a stalled worker cannot eat the box

ALLOWED_NAMES = {
    "page_view", "product_view", "search", "search_zero_results", "filter_apply",
    "config_change", "add_to_cart", "remove_from_cart", "cart_view",
    "checkout_start", "checkout_step", "checkout_error", "purchase",
    "wishlist_add", "wall_preview_open", "newsletter_submit", "outbound_click",
}

BOT_PATTERN = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|headless|lighthouse|pingdom|curl|wget|python-requests",
    re.I,
)
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BODY
init_request_id(app)

_client = None
_accepted = _rejected = _dropped = 0


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6380/0"))
    return _client


def daily_salt() -> bytes:
    """A random salt per UTC day, held only in Redis with a short TTL.

    Deriving the salt from a long-lived seed would make every past visitor
    re-identifiable by anyone holding that seed. Generating it and letting it
    expire means yesterday's visitors are cryptographically unlinkable.
    The seed is only a fallback for when Redis is unreachable.
    """
    key = "fo:salt:" + datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        conn = client()
        salt = conn.get(key)
        if salt is None:
            salt = secrets.token_bytes(32)
            # NX: two workers racing on the first event of the day must agree.
            if conn.set(key, salt, ex=36 * 3600, nx=True):
                return salt
            salt = conn.get(key)
        return salt
    except redis.RedisError:
        seed = os.environ.get("EVENT_SALT_SEED", "")
        return hashlib.sha256((seed + key).encode()).digest()


def visitor_hash(ip: str, user_agent: str) -> str:
    return hashlib.sha256(daily_salt() + ip.encode() + user_agent.encode()).hexdigest()


def parse_ua(user_agent: str) -> tuple[str, str, str]:
    """Crude on purpose. A UA-parsing dependency is a monthly regex update we
    would have to babysit for three columns nobody segments on precisely."""
    ua = user_agent.lower()
    if "ipad" in ua or ("android" in ua and "mobile" not in ua) or "tablet" in ua:
        device = "tablet"
    elif "mobi" in ua or "iphone" in ua or "android" in ua:
        device = "mobile"
    else:
        device = "desktop"

    browser = next((b for b in ("edg", "chrome", "safari", "firefox") if b in ua), "other")
    browser = {"edg": "edge"}.get(browser, browser)
    if browser == "safari" and "chrome" in ua:
        browser = "chrome"

    os_name = next((o for o in ("windows", "android", "iphone", "ipad", "mac", "linux") if o in ua), "other")
    os_name = {"iphone": "ios", "ipad": "ios", "mac": "macos"}.get(os_name, os_name)
    return device, browser, os_name


def clean(event: dict, ip: str, user_agent: str) -> dict | None:
    name = event.get("name")
    if name not in ALLOWED_NAMES:
        return None
    event_id = str(event.get("event_id", ""))
    session_id = str(event.get("session_id", ""))
    if not UUID_PATTERN.match(event_id) or not UUID_PATTERN.match(session_id):
        return None

    try:
        occurred_at = float(event.get("occurred_at", 0)) / 1000
    except (TypeError, ValueError):
        return None
    now = time.time()
    # Client clocks lie. Anything more than a day out, or in the future, is junk.
    if not (now - 86400 < occurred_at < now + 300):
        occurred_at = now

    device, browser, os_name = parse_ua(user_agent)
    props = event.get("props")
    if not isinstance(props, dict):
        props = {}

    def as_int(key):
        try:
            return int(event[key])
        except (KeyError, TypeError, ValueError):
            return None

    return {
        "event_id": event_id,
        "occurred_at": datetime.fromtimestamp(occurred_at, timezone.utc).isoformat(),
        "session_id": session_id,
        "visitor_hash": visitor_hash(ip, user_agent),
        "name": name,
        "path": str(event.get("path", ""))[:500],
        "product_id": as_int("product_id"),
        "variant_id": as_int("variant_id"),
        "cart_id": as_int("cart_id"),
        "device": device, "browser": browser, "os": os_name,
        "country": (request.headers.get("CF-IPCountry") or "")[:2].upper() or None,
        "referrer_host": str(event.get("referrer_host", ""))[:255] or None,
        "utm": json.dumps(event.get("utm") or {}),
        "props": json.dumps(props)[:8000],
    }


@app.after_request
def cors(response):
    origins = {o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()}
    origin = request.headers.get("Origin", "")
    if origin in origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.route("/e", methods=["POST", "OPTIONS"])
def collect():
    global _accepted, _rejected, _dropped
    if request.method == "OPTIONS":
        return "", 204

    user_agent = request.headers.get("User-Agent", "")
    if BOT_PATTERN.search(user_agent):
        _dropped += 1
        return "", 204                                  # crawlers get a 204, not a metric

    payload = request.get_json(silent=True)
    if payload is None:
        _rejected += 1
        return "", 204                                  # beacons cannot retry; never 4xx them
    events = payload if isinstance(payload, list) else [payload]

    ip = request.headers.get("CF-Connecting-IP") or request.remote_addr or ""
    cleaned = [c for c in (clean(e, ip, user_agent) for e in events[:MAX_BATCH]) if c]
    _rejected += len(events) - len(cleaned)
    if not cleaned:
        return "", 204

    try:
        conn = client()
        pipe = conn.pipeline()
        for event in cleaned:
            # Redis stream fields cannot be None -- redis-py raises DataError,
            # which is a RedisError, so the whole batch would vanish down the
            # "buffer unavailable" path below. Absent means absent.
            pipe.xadd(
                STREAM,
                {k: v for k, v in event.items() if v is not None},
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
        pipe.execute()
        _accepted += len(cleaned)
    except redis.RedisError:
        # Analytics is never allowed to be the reason a page fails. Losing a
        # beacon is acceptable; the alert on stream lag is how we find out.
        log.exception("event buffer unavailable, dropping %d events", len(cleaned))
        _dropped += len(cleaned)
    return "", 204


@app.get("/metrics")
def metrics():
    try:
        depth = client().xlen(STREAM)
    except redis.RedisError:
        depth = -1
    body = (
        "# TYPE fo_collector_events_accepted counter\n"
        f"fo_collector_events_accepted {_accepted}\n"
        "# TYPE fo_collector_events_rejected counter\n"
        f"fo_collector_events_rejected {_rejected}\n"
        "# TYPE fo_collector_events_dropped counter\n"
        f"fo_collector_events_dropped {_dropped}\n"
        "# TYPE fo_event_stream_depth gauge\n"
        f"fo_event_stream_depth {depth}\n"
    )
    return body, 200, {"Content-Type": "text/plain; version=0.0.4"}


def _ready():
    client().ping()
    return {"ready": True}


init_health(app, ready_check=_ready)
