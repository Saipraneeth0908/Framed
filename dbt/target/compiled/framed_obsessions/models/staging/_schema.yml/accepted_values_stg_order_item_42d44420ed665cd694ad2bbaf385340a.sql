
    
    

with all_values as (

    select
        production_status as value_field,
        count(*) as n_records

    from "framedobsessions"."stg"."stg_order_items"
    group by production_status

)

select *
from all_values
where value_field not in (
    'queued','blocked','printing','printed','mounting','framing','qc','reprint','packed','cancelled'
)


