
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    session_key as unique_field,
    count(*) as n_records

from "framedobsessions"."stg"."stg_sessions"
where session_key is not null
group by session_key
having count(*) > 1



  
  
      
    ) dbt_internal_test