
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        payment_status as value_field,
        count(*) as n_records

    from "framedobsessions"."stg"."stg_orders"
    group by payment_status

)

select *
from all_values
where value_field not in (
    'unpaid','authorized','paid','partially_refunded','refunded','failed'
)



  
  
      
    ) dbt_internal_test