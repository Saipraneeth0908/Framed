{{ config(materialized='table') }}
-- Split by where the customer stopped: "never added" is a merchandising
-- problem, "left at checkout" is a checkout problem. One blended abandonment
-- rate tells the owner which of those to fix -- neither.
select
    created_at::date        as day,
    outcome,
    count(*)                as carts,
    sum(value_cents)        as value_cents,
    sum(total_qty)          as units,
    round(avg(value_cents)) as avg_value_cents
from {{ ref('int_cart_lifecycle') }}
group by 1, 2
