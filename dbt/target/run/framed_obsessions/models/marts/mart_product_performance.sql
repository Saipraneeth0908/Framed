
  
    

  create  table "framedobsessions"."mart"."mart_product_performance__dbt_tmp"
  
  
    as
  
  (
    
with sold as (
    select
        i.product_id, i.sku, i.product_name, i.frame, i.size,
        sum(i.qty)                 as units,
        sum(i.revenue_cents)       as revenue_cents,
        sum(i.margin_cents)        as margin_cents,
        count(distinct i.order_id) as orders
    from "framedobsessions"."stg"."stg_order_items" i
    join "framedobsessions"."stg"."stg_orders" o on o.order_id = i.order_id and o.is_revenue
    group by 1, 2, 3, 4, 5
),
viewed as (
    select product_id, count(*) as views, count(distinct session_id) as viewing_sessions
    from "framedobsessions"."stg"."stg_events"
    where event_name = 'product_view' and product_id is not null
    group by 1
)
select
    coalesce(s.product_id, v.product_id) as product_id,
    s.sku, s.product_name, s.frame, s.size,
    coalesce(s.units, 0)         as units,
    coalesce(s.revenue_cents, 0) as revenue_cents,
    coalesce(s.margin_cents, 0)  as margin_cents,
    coalesce(s.orders, 0)        as orders,
    coalesce(v.views, 0)         as views,
    -- View-to-purchase separates "people look and do not buy" from "nobody
    -- looks". Those need opposite fixes.
    round(100.0 * coalesce(s.orders, 0) / nullif(v.viewing_sessions, 0), 2) as view_to_purchase_pct
from sold s
full outer join viewed v on v.product_id = s.product_id
  );
  