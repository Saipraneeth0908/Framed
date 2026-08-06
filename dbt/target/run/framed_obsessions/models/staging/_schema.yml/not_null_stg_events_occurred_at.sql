
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select occurred_at
from "framedobsessions"."stg"."stg_events"
where occurred_at is null



  
  
      
    ) dbt_internal_test