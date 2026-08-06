
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select cart_id
from "framedobsessions"."stg"."stg_carts"
where cart_id is null



  
  
      
    ) dbt_internal_test