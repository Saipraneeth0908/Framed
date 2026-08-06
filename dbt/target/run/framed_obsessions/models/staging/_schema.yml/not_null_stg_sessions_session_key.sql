
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select session_key
from "framedobsessions"."stg"."stg_sessions"
where session_key is null



  
  
      
    ) dbt_internal_test