select
    c.id                as cart_id,
    c.public_id,
    c.customer_id,
    c.email,
    c.state::text       as state,
    c.session_id,
    c.created_at,
    c.last_activity_at,
    c.converted_at,
    c.abandoned_at,
    coalesce(i.line_count, 0)  as line_count,
    coalesce(i.qty, 0)         as total_qty,
    coalesce(i.value_cents, 0) as value_cents
from "framedobsessions"."store"."carts" c
left join (
    select cart_id, count(*) as line_count, sum(qty) as qty,
           sum(qty * unit_price_cents) as value_cents
    from "framedobsessions"."store"."cart_items" group by cart_id
) i on i.cart_id = c.id