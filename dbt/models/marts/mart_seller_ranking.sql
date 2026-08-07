{{ config(materialized='table', tags=['hourly']) }}
-- Best and worst sellers in one table, ranked three ways.
--
-- Three ranks because they disagree, and the disagreement is the insight: the
-- unit leader is often not the margin leader, and a product that converts
-- brilliantly on tiny traffic is a merchandising opportunity rather than a
-- best seller.
with ranked as (
    select
        j.*,
        rank() over (order by j.units_sold desc)    as rank_by_units,
        rank() over (order by j.revenue_cents desc) as rank_by_revenue,
        rank() over (order by j.margin_cents desc)  as rank_by_margin,
        rank() over (order by coalesce(j.view_to_order_pct, -1) desc) as rank_by_conversion,
        count(*) over ()                            as catalog_size
    from {{ ref('mart_product_journey') }} j
)
select
    product_id, product_name, category, slug,
    views, cart_adds, orders, units_sold, revenue_cents, margin_cents,
    view_to_order_pct, avg_seconds_on_page, verdict,
    rank_by_units, rank_by_revenue, rank_by_margin, rank_by_conversion, catalog_size,
    -- Margin per unit says whether volume is worth having. A best seller that
    -- earns less per frame than a slow mover is a pricing decision, not a win.
    case when units_sold > 0 then round(margin_cents::numeric / units_sold) end as margin_per_unit_cents,
    case
        when rank_by_units <= greatest(3, catalog_size / 5)                    then 'best_seller'
        when units_sold = 0 and views > 0                                      then 'never_sold'
        when rank_by_units > catalog_size - greatest(3, catalog_size / 5)      then 'worst_seller'
        else 'mid'
    end as band
from ranked
