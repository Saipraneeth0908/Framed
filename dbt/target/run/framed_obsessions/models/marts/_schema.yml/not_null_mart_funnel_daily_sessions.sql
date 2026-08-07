
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select sessions
from "framedobsessions"."mart"."mart_funnel_daily"
where sessions is null



  
  
      
    ) dbt_internal_test