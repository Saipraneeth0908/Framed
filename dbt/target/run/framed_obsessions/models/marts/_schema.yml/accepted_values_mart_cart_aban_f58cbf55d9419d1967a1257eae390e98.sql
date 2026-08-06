
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        outcome as value_field,
        count(*) as n_records

    from "framedobsessions"."mart"."mart_cart_abandonment"
    group by outcome

)

select *
from all_values
where value_field not in (
    'converted','never_added','left_at_checkout','left_with_cart','active'
)



  
  
      
    ) dbt_internal_test