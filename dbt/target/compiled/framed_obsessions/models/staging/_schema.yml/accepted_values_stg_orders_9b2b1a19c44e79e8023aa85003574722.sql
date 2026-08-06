
    
    

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


