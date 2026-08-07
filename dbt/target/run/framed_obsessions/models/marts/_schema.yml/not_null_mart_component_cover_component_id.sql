
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select component_id
from "framedobsessions"."mart"."mart_component_cover"
where component_id is null



  
  
      
    ) dbt_internal_test