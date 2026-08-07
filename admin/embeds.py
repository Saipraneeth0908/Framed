"""Metabase signed static embedding.

The owner should see one product, not two logins. Metabase OSS signs a JWT with
the dashboard id and locked filter params; the admin app decides which dashboard
tokens it is willing to mint, so RBAC stays in one place.

Honest limitation: interactive embedding and row-level sandboxing are paid
tiers. Neither is needed here -- one tenant, one owner, and the Flask app gates
which dashboards each role can see.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import jwt


@dataclass(frozen=True)
class Dashboard:
    key: str
    title: str
    blurb: str
    metabase_id: int


# Dashboard ids are assigned by Metabase on first setup; override per install
# with FO_DASHBOARD_<KEY>=<id>.
CATALOGUE = [
    Dashboard("kpis", "Daily KPIs", "Revenue, orders, AOV and margin by day.", 1),
    Dashboard("funnel", "Funnel & abandonment", "View to cart to checkout to paid, plus the three drop-offs.", 2),
    Dashboard("demand", "Product demand", "Best sellers, zero-result searches and lost demand.", 3),
    Dashboard("margin", "Margin by product", "Revenue minus frozen BOM cost, per variant.", 4),
    Dashboard("cohorts", "Customer cohorts", "Repeat rate and LTV by acquisition month.", 5),
    Dashboard("ops", "Workshop throughput", "Station timings, blocked rate and reprints.", 6),
]

EXPIRY_SECONDS = 10 * 60


def embedding_configured() -> bool:
    return bool(os.environ.get("METABASE_EMBED_SECRET") and os.environ.get("METABASE_SITE_URL"))


def dashboards() -> list[Dashboard]:
    return [
        Dashboard(d.key, d.title, d.blurb, int(os.environ.get(f"FO_DASHBOARD_{d.key.upper()}", d.metabase_id)))
        for d in CATALOGUE
    ]


def embed_url(dashboard: Dashboard, params: dict | None = None) -> str | None:
    """Short-lived signed URL. Ten minutes is long enough to read a dashboard
    and short enough that a leaked URL is worthless by the time it is shared."""
    if not embedding_configured():
        return None
    token = jwt.encode(
        {
            "resource": {"dashboard": dashboard.metabase_id},
            "params": params or {},
            "exp": int(time.time()) + EXPIRY_SECONDS,
        },
        os.environ["METABASE_EMBED_SECRET"],
        algorithm="HS256",
    )
    site = os.environ["METABASE_SITE_URL"].rstrip("/")
    return f"{site}/embed/dashboard/{token}#bordered=false&titled=false&theme=night"
