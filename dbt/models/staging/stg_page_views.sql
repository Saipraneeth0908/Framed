-- One row per page a session actually looked at, with how long they looked.
--
-- Dwell is taken as the MAX active_seconds reported for that (session, path),
-- not the sum. A visitor who leaves a tab, comes back and leaves again emits
-- several page_exit events, each carrying a running total of *visible* time --
-- summing them would triple-count the same attention. Wall-clock is not used at
-- all: a tab left open over lunch is not ninety minutes of interest.
with signals as (
    select
        session_id,
        path,
        occurred_at,
        event_name,
        coalesce((props ->> 'active_seconds')::int, 0) as active_seconds,
        coalesce((props ->> 'scroll_pct')::int, 0)     as scroll_pct,
        coalesce((props ->> 'clicks')::int, 0)         as clicks,
        props ->> 'page'                                as page_kind,
        visitor_key,
        device,
        utm_source
    from {{ ref('stg_events') }}
    where event_name in ('page_view', 'page_exit', 'page_heartbeat')
      and path is not null
)
select
    session_id,
    path,
    min(page_kind)                        as page_kind,
    min(visitor_key)                      as visitor_key,
    min(device)                           as device,
    min(utm_source)                       as utm_source,
    min(occurred_at)                      as entered_at,
    max(occurred_at)                      as left_at,
    max(active_seconds)                   as active_seconds,
    max(scroll_pct)                       as scroll_pct,
    max(clicks)                           as clicks,
    -- No exit or heartbeat ever arrived: the visitor closed the tab so fast the
    -- beacon never fired, or the browser blocked it. Counted separately rather
    -- than silently recorded as zero seconds of interest.
    bool_or(event_name in ('page_exit', 'page_heartbeat')) as has_duration
from signals
group by session_id, path
