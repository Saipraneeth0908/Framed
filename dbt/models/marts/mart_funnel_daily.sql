{{ config(materialized='table', tags=['realtime']) }}
select
    day,
    device,
    utm_source,
    count(*)              as sessions,
    sum(reached_product)  as viewed_product,
    sum(reached_cart)     as added_to_cart,
    sum(reached_checkout) as started_checkout,
    sum(reached_purchase) as purchased,
    round(100.0 * sum(reached_purchase) / nullif(count(*), 0), 2) as conversion_pct
from {{ ref('int_funnel_steps') }}
group by day, device, utm_source
