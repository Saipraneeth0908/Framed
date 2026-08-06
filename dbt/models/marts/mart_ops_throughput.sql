{{ config(materialized='table') }}
select
    created_at::date as day,
    from_station,
    to_station,
    count(*)         as transitions,
    round(avg(extract(epoch from time_in_previous_station) / 3600.0)::numeric, 2) as avg_hours_in_previous,
    round((percentile_cont(0.95) within group (
        order by extract(epoch from time_in_previous_station) / 3600.0))::numeric, 2) as p95_hours_in_previous
from {{ ref('int_production_timings') }}
where time_in_previous_station is not null
group by 1, 2, 3
