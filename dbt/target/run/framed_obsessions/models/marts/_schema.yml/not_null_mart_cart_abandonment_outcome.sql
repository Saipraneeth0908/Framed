
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select outcome
from "framedobsessions"."mart"."mart_cart_abandonment"
where outcome is null



  
  
      
    ) dbt_internal_test