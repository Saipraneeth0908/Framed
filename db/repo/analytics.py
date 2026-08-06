"""Analytics reads for the admin dashboard.

Two sources, chosen per question:

* **marts** for anything that aggregates behaviour. Refreshed by dbt on a
  schedule, so these are minutes old, never seconds.
* **OLTP** for anything the owner acts on right now -- live carts, today's
  orders. A cart holder they might phone is useless at fifteen minutes stale.

Every mart-backed function degrades to an empty result if dbt has not run yet,
so a fresh install shows an honest "no data" panel rather than a 500.
"""

from __future__ import annotations

import logging

from db.conn import Role, tx

log = logging.getLogger(__name__)
ADMIN = Role.ADMIN

# Marts the dashboard reads. Checked once per request rather than per query.
REQUIRED_MARTS = (
    "mart_daily_kpis", "mart_visitor_sessions", "mart_page_engagement",
    "mart_product_journey", "mart_seller_ranking", "mart_abandoned_interest",
    "mart_click_targets", "mart_hourly_traffic", "mart_funnel_daily",
    "mart_traffic_daily", "mart_search_demand", "mart_lost_demand",
    "mart_cart_abandonment", "mart_customer_cohorts",
)


def marts_ready() -> dict[str, bool]:
    with tx(ADMIN) as cur:
        cur.execute(
            "select m as name, to_regclass('mart.' || m) is not null as ok "
            "from unnest(%s::text[]) m",
            (list(REQUIRED_MARTS),),
        )
        return {r["name"]: r["ok"] for r in cur.fetchall()}


def _query(sql: str, params: tuple | dict | None = None, mart: str | None = None) -> list[dict]:
    """Run a mart query, returning [] rather than raising when it is not built."""
    try:
        with tx(ADMIN) as cur:
            if mart:
                cur.execute("select to_regclass('mart.' || %s) is not null as ok", (mart,))
                if not cur.fetchone()["ok"]:
                    return []
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception:                                    # noqa: BLE001
        log.exception("analytics query failed (mart=%s)", mart)
        return []


def _one(sql: str, params=None, mart: str | None = None) -> dict:
    rows = _query(sql, params, mart)
    return rows[0] if rows else {}


# --------------------------------------------------------------------------- #
# Headline
# --------------------------------------------------------------------------- #

def headline(days: int = 30) -> dict:
    return _one(
        """
        select
          count(*)                                         as sessions,
          count(distinct visitor_key)                      as visitors,
          count(*) filter (where purchased)                as converting_sessions,
          round(100.0 * count(*) filter (where purchased) / nullif(count(*), 0), 2) as conversion_pct,
          round(avg(engaged_seconds))                      as avg_engaged_seconds,
          round((percentile_cont(0.5) within group (order by engaged_seconds))::numeric) as median_engaged_seconds,
          round(avg(pages_seen), 1)                        as avg_pages,
          round(avg(click_count), 1)                       as avg_clicks,
          sum(order_cents)                                 as revenue_cents,
          round(100.0 * count(*) filter (where depth_band = 'bounce') / nullif(count(*), 0), 1) as bounce_pct,
          count(*) filter (where added_to_cart and not purchased) as carted_not_bought,
          count(*) filter (where saved_design and not purchased)  as saved_not_bought
        from mart.mart_visitor_sessions
        where started_at > now() - (%(days)s || ' days')::interval
        """,
        {"days": days},
        mart="mart_visitor_sessions",
    )


def sessions_by_day(days: int = 30) -> list[dict]:
    return _query(
        """
        select d::date as day,
               count(s.session_key)                   as sessions,
               count(s.session_key) filter (where s.purchased) as purchases,
               coalesce(sum(s.order_cents), 0)        as revenue_cents,
               coalesce(round(avg(s.engaged_seconds)), 0) as avg_engaged_seconds
          from generate_series(current_date - (%(days)s - 1), current_date, interval '1 day') d
          left join mart.mart_visitor_sessions s on s.day = d::date
         group by d order by d
        """,
        {"days": days},
        mart="mart_visitor_sessions",
    )


def funnel(days: int = 30) -> list[dict]:
    """Session-level funnel. Cumulative, so each step is a subset of the last."""
    row = _one(
        """
        select
          count(*)                                              as landed,
          count(*) filter (where saw_product or added_to_cart or started_checkout or purchased) as viewed,
          count(*) filter (where added_to_cart or started_checkout or purchased) as carted,
          count(*) filter (where started_checkout or purchased) as checkout,
          count(*) filter (where purchased)                     as bought
        from mart.mart_visitor_sessions
        where started_at > now() - (%(days)s || ' days')::interval
        """,
        {"days": days},
        mart="mart_visitor_sessions",
    )
    if not row:
        return []
    steps = [
        ("Landed", row["landed"]), ("Viewed a product", row["viewed"]),
        ("Added to cart", row["carted"]), ("Started checkout", row["checkout"]),
        ("Bought", row["bought"]),
    ]
    top = steps[0][1] or 1
    out = []
    for i, (label, value) in enumerate(steps):
        previous = steps[i - 1][1] if i else value
        out.append({
            "label": label, "value": value,
            "pct_of_top": round(100.0 * value / top, 1),
            "drop": (previous - value) if i else 0,
            "drop_pct": round(100.0 * (previous - value) / previous, 1) if i and previous else 0.0,
        })
    return out


def outcomes(days: int = 30) -> list[dict]:
    return _query(
        """
        select outcome, count(*) as sessions, coalesce(sum(order_cents), 0) as revenue_cents
          from mart.mart_visitor_sessions
         where started_at > now() - (%(days)s || ' days')::interval
         group by outcome order by sessions desc
        """,
        {"days": days},
        mart="mart_visitor_sessions",
    )


def depth_bands(days: int = 30) -> list[dict]:
    return _query(
        """
        select depth_band,
               count(*) as sessions,
               round(100.0 * count(*) filter (where purchased) / nullif(count(*), 0), 1) as conversion_pct,
               round(avg(pages_seen), 1) as avg_pages
          from mart.mart_visitor_sessions
         where started_at > now() - (%(days)s || ' days')::interval
         group by depth_band
         order by case depth_band when 'bounce' then 1 when 'glance' then 2
                                  when 'browse' then 3 else 4 end
        """,
        {"days": days},
        mart="mart_visitor_sessions",
    )


# --------------------------------------------------------------------------- #
# Behaviour
# --------------------------------------------------------------------------- #

def page_engagement(limit: int = 20) -> list[dict]:
    return _query(
        """select * from mart.mart_page_engagement
            order by views desc limit %s""",
        (limit,), mart="mart_page_engagement",
    )


def click_targets(limit: int = 20) -> list[dict]:
    return _query(
        """select target, label, from_path, event_name,
                  sum(clicks) as clicks, sum(sessions) as sessions
             from mart.mart_click_targets
            group by target, label, from_path, event_name
            order by clicks desc limit %s""",
        (limit,), mart="mart_click_targets",
    )


def hourly_heatmap() -> list[dict]:
    return _query(
        "select * from mart.mart_hourly_traffic order by dow, hour",
        mart="mart_hourly_traffic",
    )


def device_split(days: int = 30) -> list[dict]:
    return _query(
        """select device, count(*) as sessions,
                  round(100.0 * count(*) filter (where purchased) / nullif(count(*), 0), 1) as conversion_pct,
                  round(avg(engaged_seconds)) as avg_engaged_seconds
             from mart.mart_visitor_sessions
            where started_at > now() - (%(days)s || ' days')::interval
            group by device order by sessions desc""",
        {"days": days}, mart="mart_visitor_sessions",
    )


def acquisition(days: int = 30) -> list[dict]:
    return _query(
        """select coalesce(utm_source, 'direct') as source,
                  coalesce(referrer_host, '')    as referrer,
                  count(*) as sessions,
                  count(*) filter (where purchased) as purchases,
                  coalesce(sum(order_cents), 0)  as revenue_cents,
                  round(100.0 * count(*) filter (where purchased) / nullif(count(*), 0), 1) as conversion_pct,
                  round(avg(engaged_seconds))    as avg_engaged_seconds
             from mart.mart_visitor_sessions
            where started_at > now() - (%(days)s || ' days')::interval
            group by 1, 2 order by sessions desc limit 20""",
        {"days": days}, mart="mart_visitor_sessions",
    )


def landing_pages(limit: int = 10) -> list[dict]:
    return _query(
        """select landing_path, count(*) as sessions,
                  round(100.0 * count(*) filter (where purchased) / nullif(count(*), 0), 1) as conversion_pct,
                  round(100.0 * count(*) filter (where depth_band = 'bounce') / nullif(count(*), 0), 1) as bounce_pct
             from mart.mart_visitor_sessions
            where landing_path is not null
            group by landing_path order by sessions desc limit %s""",
        (limit,), mart="mart_visitor_sessions",
    )


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #

def product_journey(order_by: str = "views", limit: int = 25) -> list[dict]:
    column = {
        "views": "views", "cart_adds": "cart_adds", "orders": "orders",
        "revenue": "revenue_cents", "margin": "margin_cents",
        "conversion": "view_to_order_pct", "dwell": "avg_seconds_on_page",
    }.get(order_by, "views")
    return _query(
        f"""select * from mart.mart_product_journey
             order by {column} desc nulls last limit %s""",
        (limit,), mart="mart_product_journey",
    )


def sellers(band: str, limit: int = 10) -> list[dict]:
    if band == "best":
        clause, order = "band = 'best_seller'", "rank_by_units"
    elif band == "worst":
        clause, order = "band in ('worst_seller', 'never_sold')", "units_sold, views desc"
    else:
        clause, order = "1=1", "rank_by_units"
    return _query(
        f"""select * from mart.mart_seller_ranking
             where {clause} order by {order} limit %s""",
        (limit,), mart="mart_seller_ranking",
    )


def looked_never_bought(limit: int = 12) -> list[dict]:
    return _query(
        """select product_name, slug, category, views, viewing_sessions, cart_adds,
                  wishlist_adds, avg_seconds_on_page, avg_scroll_pct, verdict
             from mart.mart_product_journey
            where orders = 0 and views > 0
            order by views desc limit %s""",
        (limit,), mart="mart_product_journey",
    )


def abandoned_interest(limit: int = 15) -> list[dict]:
    return _query(
        """select * from mart.mart_abandoned_interest
            order by abandoned_cart_adds + abandoned_saves desc limit %s""",
        (limit,), mart="mart_abandoned_interest",
    )


def search_demand(limit: int = 15) -> list[dict]:
    return _query(
        """select term, sum(searches) as searches, sum(sessions) as sessions,
                  sum(zero_result_searches) as zero_results
             from mart.mart_search_demand
            group by term order by searches desc limit %s""",
        (limit,), mart="mart_search_demand",
    )


def lost_demand(limit: int = 15) -> list[dict]:
    return _query(
        "select * from mart.mart_lost_demand order by occurrences desc limit %s",
        (limit,), mart="mart_lost_demand",
    )


# --------------------------------------------------------------------------- #
# Live -- read from OLTP, because a cart holder is only worth phoning today
# --------------------------------------------------------------------------- #

def live_carts(limit: int = 25) -> list[dict]:
    return _query(
        """
        select c.public_id::text as token, c.state::text as state, c.email::text as email,
               c.created_at, c.last_activity_at, c.session_id::text as session_id,
               count(ci.id)                        as lines,
               coalesce(sum(ci.qty), 0)            as units,
               coalesce(sum(ci.qty * ci.unit_price_cents), 0) as value_cents,
               extract(epoch from (now() - c.last_activity_at)) / 60 as idle_minutes,
               string_agg(distinct p.name, ', ' order by p.name) as products
          from store.carts c
          join store.cart_items ci on ci.cart_id = c.id
          join store.variants v on v.id = ci.variant_id
          join store.products p on p.id = v.product_id
         where c.state in ('active', 'abandoned')
         group by c.id
         order by c.last_activity_at desc
         limit %s
        """,
        (limit,),
    )


def live_totals() -> dict:
    return _one(
        """
        select
          count(*) filter (where c.state = 'active')    as active_carts,
          count(*) filter (where c.state = 'abandoned') as abandoned_carts,
          coalesce(sum(x.value_cents) filter (where c.state = 'active'), 0)    as active_value_cents,
          coalesce(sum(x.value_cents) filter (where c.state = 'abandoned'), 0) as abandoned_value_cents
        from store.carts c
        join lateral (
            select coalesce(sum(ci.qty * ci.unit_price_cents), 0) as value_cents
              from store.cart_items ci where ci.cart_id = c.id
        ) x on true
        where exists (select 1 from store.cart_items ci where ci.cart_id = c.id)
        """
    )


def events_today() -> dict:
    """Raw ingestion health, so an empty dashboard can be explained."""
    return _one(
        """
        select
          count(*)                                    as events,
          count(distinct session_id)                  as sessions,
          count(distinct name)                        as event_types,
          max(occurred_at)                            as last_event_at
        from raw.events
        where occurred_at > now() - interval '24 hours'
        """
    )
