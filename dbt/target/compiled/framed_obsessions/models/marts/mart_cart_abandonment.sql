
with __dbt__cte__int_cart_lifecycle as (
-- Three distinct abandonment points, not one number. "Abandonment" that lumps
-- them together tells the owner nothing about what to fix: never_added is a
-- merchandising problem, left_at_checkout is a checkout problem.
--
-- The session join used to be md5(session_id || ':0') -- a guess that the cart
-- belonged to a visitor's *first* session, against a session_key that was hashed
-- from the visitor id entirely. It matched nothing, so every cart fell through
-- to 'left_with_cart' and left_at_checkout was permanently zero. Now both sides
-- key on the server-minted session_id, and the cart is attributed to whichever
-- session was open when it was last touched.
with cart_session as (
    select distinct on (c.cart_id)
        c.cart_id,
        s.session_key,
        s.started_checkout,
        s.engaged_seconds,
        s.pages_seen,
        s.device,
        s.utm_source
    from "framedobsessions"."stg"."stg_carts" c
    join "framedobsessions"."stg"."stg_sessions" s
      on s.session_id = c.session_id
     and s.started_at <= c.last_activity_at
    order by c.cart_id, s.started_at desc
)
select
    c.cart_id,
    c.state,
    c.value_cents,
    c.total_qty,
    c.line_count,
    c.created_at,
    c.abandoned_at,
    c.converted_at,
    cs.session_key,
    cs.device,
    cs.utm_source,
    coalesce(cs.engaged_seconds, 0) as engaged_seconds,
    coalesce(cs.pages_seen, 0)      as pages_seen,
    case
        when c.state = 'converted'                                                then 'converted'
        when c.line_count = 0                                                     then 'never_added'
        when o.order_id is null and c.state = 'abandoned'
             and coalesce(cs.started_checkout, false)                             then 'left_at_checkout'
        when c.state = 'abandoned'                                                then 'left_with_cart'
        else 'active'
    end as outcome
from "framedobsessions"."stg"."stg_carts" c
left join "framedobsessions"."stg"."stg_orders" o on o.cart_id = c.cart_id
left join cart_session cs on cs.cart_id = c.cart_id
) -- Split by where the customer stopped: "never added" is a merchandising
-- problem, "left at checkout" is a checkout problem. One blended abandonment
-- rate tells the owner which of those to fix -- neither.
select
    created_at::date        as day,
    outcome,
    count(*)                as carts,
    sum(value_cents)        as value_cents,
    sum(total_qty)          as units,
    round(avg(value_cents)) as avg_value_cents
from __dbt__cte__int_cart_lifecycle
group by 1, 2