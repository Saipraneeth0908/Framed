
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- Each funnel step must be a subset of the one before it. A session that
-- purchased without starting checkout means the sessionization or the event
-- taxonomy is broken, and every conversion number downstream is wrong.
select
    day, device, utm_source,
    sessions, viewed_product, added_to_cart, started_checkout, purchased
from "framedobsessions"."mart"."mart_funnel_daily"
where viewed_product    > sessions
   or added_to_cart     > viewed_product
   or started_checkout  > added_to_cart
   or purchased         > started_checkout
  
  
      
    ) dbt_internal_test