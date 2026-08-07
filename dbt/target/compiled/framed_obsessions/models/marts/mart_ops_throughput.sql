
with __dbt__cte__int_production_timings as (
-- Station timings are derived from the audit log rather than a second bespoke
-- events table: the trigger already records every production_status change with
-- a before and after, so a dedicated table would be a duplicate source of truth.
with transitions as (
    select
        (a.after ->> 'id')::bigint                       as order_item_id,
        a.before ->> 'production_status'                 as from_station,
        a.after  ->> 'production_status'                 as to_station,
        a.created_at
    from "framedobsessions"."ops"."audit_log" a
    where a.entity = 'store.order_items'
      and a.action = 'update'
      and a.before ->> 'production_status' is distinct from a.after ->> 'production_status'
)
select
    order_item_id,
    from_station,
    to_station,
    created_at,
    created_at - lag(created_at) over (partition by order_item_id order by created_at) as time_in_previous_station
from transitions
) select
    created_at::date as day,
    from_station,
    to_station,
    count(*)         as transitions,
    round(avg(extract(epoch from time_in_previous_station) / 3600.0)::numeric, 2) as avg_hours_in_previous,
    round((percentile_cont(0.95) within group (
        order by extract(epoch from time_in_previous_station) / 3600.0))::numeric, 2) as p95_hours_in_previous
from __dbt__cte__int_production_timings
where time_in_previous_station is not null
group by 1, 2, 3