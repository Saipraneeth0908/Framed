
    
    

select
    ledger_id as unique_field,
    count(*) as n_records

from "framedobsessions"."stg"."stg_ledger"
where ledger_id is not null
group by ledger_id
having count(*) > 1


