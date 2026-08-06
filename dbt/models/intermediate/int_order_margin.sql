select
    o.order_id,
    o.placed_date,
    o.is_revenue,
    sum(i.revenue_cents)  as revenue_cents,
    sum(i.cogs_cents)     as cogs_cents,
    sum(i.margin_cents)   as margin_cents,
    sum(i.qty)            as units
from {{ ref('stg_orders') }} o
join {{ ref('stg_order_items') }} i on i.order_id = o.order_id
group by o.order_id, o.placed_date, o.is_revenue
