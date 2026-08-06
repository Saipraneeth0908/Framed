
    
    

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


