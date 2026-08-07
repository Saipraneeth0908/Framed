{{ config(materialized='table', tags=['realtime']) }}
-- One row per visit: how long, how deep, what they did, whether it paid.
--
-- Depth bands rather than a raw average, because session length is heavily
-- skewed -- one researcher reading for twenty minutes drags the mean somewhere
-- no actual visitor sits.
select
    s.session_key,
    s.session_id,
    s.visitor_key,
    s.started_at,
    s.started_at::date          as day,
    date_part('hour', s.started_at)::int as hour_of_day,
    s.duration_seconds,
    s.engaged_seconds,
    s.pages_seen,
    s.click_count,
    s.max_scroll_pct,
    s.device,
    s.browser,
    s.country,
    s.utm_source,
    s.referrer_host,
    s.landing_path,
    s.exit_path,
    s.saw_product,
    s.searched,
    s.saved_design,
    s.added_to_cart,
    s.started_checkout,
    s.purchased,
    case
        when s.engaged_seconds < 10                        then 'bounce'
        when s.engaged_seconds < 60                        then 'glance'
        when s.engaged_seconds < 300                       then 'browse'
        else                                                    'deep'
    end as depth_band,
    case
        when s.purchased                                   then 'bought'
        when s.started_checkout                            then 'left_at_checkout'
        when s.added_to_cart                               then 'left_with_cart'
        when s.saved_design                                then 'saved_only'
        when s.saw_product                                 then 'viewed_only'
        else                                                    'landed_only'
    end as outcome,
    o.order_id,
    coalesce(o.total_cents, 0) as order_cents
from {{ ref('stg_sessions') }} s
left join {{ ref('stg_carts') }} c on c.session_id = s.session_id
left join {{ ref('stg_orders') }} o on o.cart_id = c.cart_id and o.is_revenue
