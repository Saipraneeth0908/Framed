
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        reason as value_field,
        count(*) as n_records

    from "framedobsessions"."stg"."stg_ledger"
    group by reason

)

select *
from all_values
where value_field not in (
    'receive','consume','damage','return','correction','cancel_restock','reserve','unreserve'
)



  
  
      
    ) dbt_internal_test