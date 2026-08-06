
    
    

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


