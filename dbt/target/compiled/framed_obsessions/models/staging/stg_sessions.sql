-- Sessionization: a 30-minute inactivity gap starts a new session.
--
-- Keyed on session_id (minted server-side, shared with the cart cookie) rather
-- than on the visitor hash. The hash derives from an IP that changes when a
-- phone moves between wifi and cellular, which used to split one visit into
-- several; the server id does not move. It is also the key that lets a session
-- join to a cart, and therefore to money.
--
-- Done once here and reused by every funnel, so no two reports can disagree
-- about what a session is.
with ordered as (
    select
        *,
        lag(occurred_at) over (partition by session_id order by occurred_at) as previous_at
    from "framedobsessions"."stg"."stg_events"
),
marked as (
    select
        *,
        case
            when previous_at is null
              or occurred_at - previous_at > interval '30 minutes'
            then 1 else 0
        end as is_new_session
    from ordered
),
numbered as (
    select
        *,
        sum(is_new_session) over (partition by session_id order by occurred_at
                                  rows between unbounded preceding and current row) as session_seq
    from marked
),
engagement as (
    select
        session_id,
        sum(active_seconds) as engaged_seconds,
        sum(clicks)         as click_count,
        max(scroll_pct)     as max_scroll_pct,
        count(*)            as pages_seen
    from "framedobsessions"."stg"."stg_page_views"
    group by session_id
)
select
    n.session_id,
    n.session_seq,
    md5(n.session_id::text || ':' || n.session_seq)               as session_key,
    min(n.visitor_key)                                            as visitor_key,
    min(n.occurred_at)                                            as started_at,
    max(n.occurred_at)                                            as ended_at,
    extract(epoch from (max(n.occurred_at) - min(n.occurred_at))) as duration_seconds,
    -- Engaged seconds is time the tab was actually visible. Duration is the
    -- span from first to last event. Reporting only the second flatters us.
    coalesce(min(e.engaged_seconds), 0)                           as engaged_seconds,
    coalesce(min(e.click_count), 0)                               as click_count,
    coalesce(min(e.max_scroll_pct), 0)                            as max_scroll_pct,
    coalesce(min(e.pages_seen), count(distinct n.path))           as pages_seen,
    count(*)                                                      as event_count,
    min(n.device)                                                 as device,
    min(n.browser)                                                as browser,
    min(n.os)                                                     as os,
    min(n.country)                                                as country,
    min(n.utm_source)                                             as utm_source,
    min(n.referrer_host)                                          as referrer_host,
    (array_agg(n.path order by n.occurred_at) filter (where n.path is not null))[1]      as landing_path,
    (array_agg(n.path order by n.occurred_at desc) filter (where n.path is not null))[1] as exit_path,
    bool_or(n.event_name = 'product_view')                        as saw_product,
    bool_or(n.event_name in ('search', 'search_zero_results'))    as searched,
    bool_or(n.event_name = 'wishlist_add')                        as saved_design,
    bool_or(n.event_name = 'add_to_cart')                         as added_to_cart,
    bool_or(n.event_name = 'checkout_start')                      as started_checkout,
    bool_or(n.event_name = 'purchase')                            as purchased
from numbered n
left join engagement e on e.session_id = n.session_id
group by n.session_id, n.session_seq