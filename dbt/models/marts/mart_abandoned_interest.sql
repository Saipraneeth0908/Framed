{{ config(materialized='table', tags=['realtime']) }}
-- Declared intent that never became money, per product.
--
-- A visitor who adds to a cart or saves a design has told us exactly what they
-- want. Every row here is a specific thing someone wanted and did not get, which
-- makes this the most directly actionable table in the warehouse.
with intent as (
    select
        e.session_id,
        e.occurred_at,
        e.event_name,
        coalesce(
            nullif(e.props ->> 'slug', ''),
            case when e.path like '/product/%' then substring(e.path from 10) end
        ) as slug
    from {{ ref('stg_events') }} e
    where e.event_name in ('add_to_cart', 'wishlist_add')
),
purchased_sessions as (
    -- A session that bought *something* is not an abandonment of the whole
    -- visit, but it can still have abandoned a specific product. Both are
    -- tracked, and the per-product one is what the columns below count.
    select distinct session_id from {{ ref('stg_sessions') }} where purchased
),
bought as (
    select distinct c.session_id, p.slug
    from {{ ref('stg_order_items') }} i
    join {{ ref('stg_orders') }} o on o.order_id = i.order_id and o.is_revenue
    join {{ ref('stg_carts') }} c on c.cart_id = o.cart_id
    join {{ source('store', 'products') }} p on p.id = i.product_id
    where c.session_id is not null
),
abandoned as (
    select
        i.slug,
        i.session_id,
        i.event_name,
        i.occurred_at,
        (ps.session_id is not null) as session_bought_something
    from intent i
    left join bought b on b.session_id = i.session_id and b.slug = i.slug
    left join purchased_sessions ps on ps.session_id = i.session_id
    where i.slug is not null
      and b.slug is null                    -- this exact product was never bought
)
select
    p.id                    as product_id,
    p.name                  as product_name,
    p.category,
    a.slug,
    count(*) filter (where a.event_name = 'add_to_cart')  as abandoned_cart_adds,
    count(*) filter (where a.event_name = 'wishlist_add') as abandoned_saves,
    count(distinct a.session_id)                          as sessions,
    count(distinct a.session_id) filter (where a.session_bought_something) as sessions_that_bought_else,
    max(a.occurred_at)                                    as last_abandoned_at,
    -- Value at stake: what these carts would have been worth at the cheapest
    -- configuration. Deliberately the floor, not an average -- an inflated
    -- "lost revenue" number is how a recovery campaign gets over-funded.
    count(*) filter (where a.event_name = 'add_to_cart')
        * (select min(v.price_cents) from {{ source('store', 'variants') }} v
            where v.product_id = p.id and v.archived_at is null) as floor_value_cents
from abandoned a
join {{ source('store', 'products') }} p on p.slug = a.slug
group by p.id, p.name, p.category, a.slug
