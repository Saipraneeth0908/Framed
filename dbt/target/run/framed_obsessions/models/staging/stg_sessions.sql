
  create view "framedobsessions"."stg"."stg_sessions__dbt_tmp"
    
    
  as (
    -- Sessionization: the one genuinely tricky model. A 30-minute inactivity gap
-- starts a new session. Done once here and reused by every funnel, so no two
-- reports can disagree about what a session is.
with ordered as (
    select
        *,
        lag(occurred_at) over (partition by visitor_key order by occurred_at) as previous_at
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
        sum(is_new_session) over (partition by visitor_key order by occurred_at
                                  rows between unbounded preceding and current row) as session_seq
    from marked
)
select
    visitor_key,
    session_seq,
    md5(visitor_key || ':' || session_seq)                     as session_key,
    min(occurred_at)                                           as started_at,
    max(occurred_at)                                           as ended_at,
    extract(epoch from (max(occurred_at) - min(occurred_at)))  as duration_seconds,
    count(*)                                                   as event_count,
    min(device)                                                as device,
    min(browser)                                               as browser,
    min(country)                                               as country,
    min(utm_source)                                            as utm_source,
    min(referrer_host)                                         as referrer_host,
    (array_agg(path order by occurred_at) filter (where path is not null))[1] as landing_path,
    (array_agg(path order by occurred_at desc) filter (where path is not null))[1] as exit_path,
    bool_or(event_name = 'product_view')    as saw_product,
    bool_or(event_name = 'add_to_cart')     as added_to_cart,
    bool_or(event_name = 'checkout_start')  as started_checkout,
    bool_or(event_name = 'purchase')        as purchased
from numbered
group by visitor_key, session_seq
  );