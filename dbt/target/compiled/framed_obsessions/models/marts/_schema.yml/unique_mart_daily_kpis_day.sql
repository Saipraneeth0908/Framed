
    
    

select
    day as unique_field,
    count(*) as n_records

from "framedobsessions"."mart"."mart_daily_kpis"
where day is not null
group by day
having count(*) > 1


