
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select revenue_cents
from "framedobsessions"."mart"."mart_daily_kpis"
where revenue_cents is null



  
  
      
    ) dbt_internal_test