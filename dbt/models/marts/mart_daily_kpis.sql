{{ config(materialized='table', tags=['realtime']) }}
-- The owner's home number. One row per day, present even on zero days, because
-- a gap in a chart reads as "broken" rather than "quiet".
with days as (
    select generate_series(
        least(coalesce((select min(placed_date) from {{ ref('stg_orders') }}), current_date),
              current_date - 89),
        current_date, interval '1 day')::date as day
)
select
    d.day,
    coalesce(count(o.order_id) filter (where o.is_revenue), 0)   as orders,
    coalesce(sum(o.total_cents) filter (where o.is_revenue), 0)  as revenue_cents,
    coalesce(sum(o.refunded_cents), 0)                           as refunded_cents,
    coalesce(sum(m.margin_cents) filter (where o.is_revenue), 0) as margin_cents,
    coalesce(sum(m.units) filter (where o.is_revenue), 0)        as units,
    case when count(o.order_id) filter (where o.is_revenue) > 0
         then round(sum(o.total_cents) filter (where o.is_revenue)
                    / count(o.order_id) filter (where o.is_revenue))
         else 0 end                                              as aov_cents,
    count(o.order_id) filter (where o.cancelled_at is not null)  as cancellations
from days d
left join {{ ref('stg_orders') }} o on o.placed_date = d.day
left join {{ ref('int_order_margin') }} m on m.order_id = o.order_id
group by d.day
