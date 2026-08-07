
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select ledger_id
from "framedobsessions"."stg"."stg_ledger"
where ledger_id is null



  
  
      
    ) dbt_internal_test