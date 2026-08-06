
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- An order whose total disagrees with its own line items means either the
-- discount arithmetic drifted or somebody edited history. Both are incidents.
with lines as (
    select order_id, sum(revenue_cents) as line_total_cents
    from "framedobsessions"."stg"."stg_order_items"
    group by order_id
)
select
    o.order_id,
    o.total_cents,
    o.subtotal_cents,
    o.discount_cents,
    l.line_total_cents
from "framedobsessions"."stg"."stg_orders" o
join lines l on l.order_id = o.order_id
where l.line_total_cents <> o.subtotal_cents
   or o.total_cents <> o.subtotal_cents - o.discount_cents + o.shipping_cents + o.tax_cents
  
  
      
    ) dbt_internal_test