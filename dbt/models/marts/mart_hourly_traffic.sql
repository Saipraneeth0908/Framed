{{ config(materialized='table', tags=['hourly']) }}
-- Day-of-week by hour-of-day. Answers when to schedule a drop, when to be at
-- the workshop, and when a quiet period is normal rather than an outage.
--
-- Every cell in the 7x24 grid exists whether or not it saw traffic: a heatmap
-- with holes in it reads as broken instrumentation.
with grid as (
    select d as dow, h as hour
    from generate_series(0, 6) d
    cross join generate_series(0, 23) h
),
observed as (
    select
        date_part('dow',  started_at)::int as dow,
        date_part('hour', started_at)::int as hour,
        count(*)                            as sessions,
        count(*) filter (where purchased)   as purchases,
        sum(order_cents)                    as revenue_cents,
        round(avg(engaged_seconds))         as avg_engaged_seconds
    from {{ ref('mart_visitor_sessions') }}
    group by 1, 2
)
select
    g.dow,
    g.hour,
    to_char(date '2026-08-02' + g.dow, 'Dy')      as day_name,
    coalesce(o.sessions, 0)                       as sessions,
    coalesce(o.purchases, 0)                      as purchases,
    coalesce(o.revenue_cents, 0)                  as revenue_cents,
    coalesce(o.avg_engaged_seconds, 0)            as avg_engaged_seconds
from grid g
left join observed o on o.dow = g.dow and o.hour = g.hour
