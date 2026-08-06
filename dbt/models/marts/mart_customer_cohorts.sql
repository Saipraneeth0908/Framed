{{ config(materialized='table') }}
select
    c.cohort_month,
    count(distinct c.customer_id)                              as customers,
    count(distinct o.order_id) filter (where o.is_revenue)     as orders,
    coalesce(sum(o.total_cents) filter (where o.is_revenue), 0) as revenue_cents,
    round(coalesce(sum(o.total_cents) filter (where o.is_revenue), 0)
          / nullif(count(distinct c.customer_id), 0))          as ltv_cents,
    round(100.0 * count(distinct o.customer_id) filter (where o.is_revenue)
          / nullif(count(distinct c.customer_id), 0), 2)       as activation_pct
from {{ ref('stg_customers') }} c
left join {{ ref('stg_orders') }} o on o.customer_id = c.customer_id
group by 1
