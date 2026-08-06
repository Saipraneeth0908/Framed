-- Three distinct abandonment points, not one number. "Abandonment" that lumps
-- them together tells the owner nothing about what to fix.
select
    c.cart_id,
    c.state,
    c.value_cents,
    c.total_qty,
    c.created_at,
    c.abandoned_at,
    c.converted_at,
    case
        when c.state = 'converted'                      then 'converted'
        when c.line_count = 0                           then 'never_added'
        when o.order_id is null and c.state = 'abandoned' and s.started_checkout then 'left_at_checkout'
        when c.state = 'abandoned'                      then 'left_with_cart'
        else 'active'
    end as outcome
from {{ ref('stg_carts') }} c
left join {{ ref('stg_orders') }} o on o.cart_id = c.cart_id
left join {{ ref('stg_sessions') }} s
       on s.session_key = md5(coalesce(c.session_id::text, '') || ':0')
