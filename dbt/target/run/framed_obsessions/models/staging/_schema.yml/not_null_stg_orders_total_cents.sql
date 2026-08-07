
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select total_cents
from "framedobsessions"."stg"."stg_orders"
where total_cents is null



  
  
      
    ) dbt_internal_test