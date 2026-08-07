{{ config(materialized='table', tags=['hourly']) }}
-- How long people spend on each page, and where they leave.
--
-- Exit rate is per page, not per session: "of the visits that reached this
-- page, what share ended here". A high exit rate on /checkout is an emergency;
-- the same number on /contact is the page doing its job.
with sessions_total as (
    select count(*) as n from {{ ref('stg_sessions') }}
)
select
    v.path,
    coalesce(min(v.page_kind), 'other')                 as page_kind,
    count(*)                                            as views,
    count(distinct v.session_id)                        as sessions,
    count(distinct v.visitor_key)                       as visitors,
    round(avg(v.active_seconds) filter (where v.has_duration))  as avg_seconds,
    round((percentile_cont(0.5) within group (
        order by v.active_seconds) filter (where v.has_duration))::numeric) as median_seconds,
    round((percentile_cont(0.9) within group (
        order by v.active_seconds) filter (where v.has_duration))::numeric) as p90_seconds,
    sum(v.active_seconds)                               as total_seconds,
    round(avg(v.scroll_pct) filter (where v.has_duration)) as avg_scroll_pct,
    sum(v.clicks)                                       as clicks,
    count(*) filter (where s.exit_path = v.path)        as exits,
    round(100.0 * count(*) filter (where s.exit_path = v.path) / nullif(count(*), 0), 1) as exit_pct,
    count(*) filter (where s.landing_path = v.path)     as entrances,
    -- A page seen with no duration signal at all: the tab closed before the
    -- beacon fired. Surfaced rather than folded into "0 seconds of interest".
    count(*) filter (where not v.has_duration)          as views_without_duration
from {{ ref('stg_page_views') }} v
left join {{ ref('stg_sessions') }} s on s.session_id = v.session_id
cross join sessions_total
group by v.path
