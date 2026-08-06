{{ config(materialized='table', tags=['hourly']) }}
-- What people actually click, by control rather than by coordinate.
--
-- A pixel heatmap is a screenshot: pretty, and impossible to act on after the
-- layout changes. "Which control, from which page, how often" survives a
-- redesign and answers the only question worth asking -- is this button doing
-- anything.
select
    e.occurred_at::date            as day,
    e.path                          as from_path,
    e.event_name,
    coalesce(
        nullif(e.props ->> 'target', ''),
        nullif(e.props ->> 'filter', ''),
        nullif(e.props ->> 'category', ''),
        nullif(e.props ->> 'slug', ''),
        'unlabelled'
    )                               as target,
    nullif(e.props ->> 'text', '')  as label,
    nullif(e.props ->> 'href', '')  as href,
    count(*)                        as clicks,
    count(distinct e.session_id)    as sessions
from {{ ref('stg_events') }} e
where e.event_name in ('click', 'product_click', 'filter_apply', 'category_switch', 'outbound_click')
group by 1, 2, 3, 4, 5, 6
