
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        fulfilment_status as value_field,
        count(*) as n_records

    from "framedobsessions"."stg"."stg_orders"
    group by fulfilment_status

)

select *
from all_values
where value_field not in (
    'unfulfilled','partially_fulfilled','fulfilled','in_transit','delivered','returned'
)



  
  
      
    ) dbt_internal_test