
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        state as value_field,
        count(*) as n_records

    from "framedobsessions"."stg"."stg_carts"
    group by state

)

select *
from all_values
where value_field not in (
    'active','converted','abandoned','expired'
)



  
  
      
    ) dbt_internal_test