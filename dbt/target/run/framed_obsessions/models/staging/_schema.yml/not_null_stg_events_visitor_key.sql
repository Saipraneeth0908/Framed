
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select visitor_key
from "framedobsessions"."stg"."stg_events"
where visitor_key is null



  
  
      
    ) dbt_internal_test