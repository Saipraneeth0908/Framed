
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select orders
from "framedobsessions"."mart"."mart_daily_kpis"
where orders is null



  
  
      
    ) dbt_internal_test