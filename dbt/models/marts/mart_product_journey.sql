{{ config(materialized='table', tags=['hourly']) }}
-- The full path for one product: seen on a card, clicked, viewed, configured,
-- saved, added to cart, bought. Every drop-off between two adjacent steps is a
-- different problem with a different fix.
select
    i.product_id,
    i.product_name,
    i.category,
    i.slug,
    i.card_clicks,
    i.views,
    i.viewing_sessions,
    i.config_changes,
    i.wishlist_adds,
    i.cart_adds,
    i.adding_sessions,
    i.cart_removals,
    i.orders,
    i.units_sold,
    i.revenue_cents,
    i.margin_cents,
    i.avg_seconds_on_page,
    i.median_seconds_on_page,
    i.avg_scroll_pct,

    -- Rates, each guarded against a zero denominator so an unseen product
    -- reports null rather than a fake 0% that ranks it alongside a real failure.
    round(100.0 * i.cart_adds / nullif(i.views, 0), 1)          as view_to_cart_pct,
    round(100.0 * i.orders   / nullif(i.cart_adds, 0), 1)       as cart_to_order_pct,
    round(100.0 * i.orders   / nullif(i.viewing_sessions, 0), 1) as view_to_order_pct,
    round(100.0 * i.wishlist_adds / nullif(i.views, 0), 1)      as view_to_save_pct,

    -- Interest that never converted. This is the actionable number: high views
    -- and zero orders is a pricing or imagery problem, not a traffic problem.
    greatest(i.cart_adds - i.orders, 0)                         as adds_never_ordered,
    case
        when i.views = 0 and i.units_sold > 0            then 'sold_unwatched'
        when i.views >= 20 and i.orders = 0              then 'looked_never_bought'
        when i.cart_adds > 0 and i.orders = 0            then 'carted_never_bought'
        when i.orders > 0                                then 'converting'
        when i.views > 0                                 then 'browsed_only'
        else 'no_signal'
    end                                                          as verdict,
    i.last_seen_at
from {{ ref('int_product_interest') }} i
