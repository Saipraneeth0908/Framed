-- Everything a visitor did to a product, keyed by slug so behaviour joins to
-- the catalog and to money in one place.
--
-- Slug rather than product_id: the beacon knows the URL, not our primary key,
-- and resolving it here once keeps every downstream model honest.
with events as (
    select
        e.session_id,
        e.occurred_at,
        e.event_name,
        coalesce(
            nullif(e.props ->> 'slug', ''),
            case when e.path like '/product/%' then substring(e.path from 10) end
        ) as slug
    from {{ ref('stg_events') }} e
    where e.event_name in ('product_view', 'product_click', 'add_to_cart',
                           'wishlist_add', 'config_change', 'remove_from_cart')
),
resolved as (
    select ev.*, p.id as product_id, p.name as product_name, p.category
    from events ev
    join {{ source('store', 'products') }} p on p.slug = ev.slug
    where ev.slug is not null
),
per_product as (
    select
        product_id,
        product_name,
        category,
        slug,
        count(*) filter (where event_name = 'product_view')     as views,
        count(*) filter (where event_name = 'product_click')    as card_clicks,
        count(*) filter (where event_name = 'config_change')    as config_changes,
        count(*) filter (where event_name = 'add_to_cart')      as cart_adds,
        count(*) filter (where event_name = 'wishlist_add')     as wishlist_adds,
        count(*) filter (where event_name = 'remove_from_cart') as cart_removals,
        count(distinct session_id) filter (where event_name = 'product_view')  as viewing_sessions,
        count(distinct session_id) filter (where event_name = 'add_to_cart')   as adding_sessions,
        count(distinct session_id) filter (where event_name = 'wishlist_add')  as saving_sessions,
        max(occurred_at)                                        as last_seen_at
    from resolved
    group by product_id, product_name, category, slug
),
dwell as (
    select
        p.id as product_id,
        round(avg(v.active_seconds))                              as avg_seconds_on_page,
        round((percentile_cont(0.5) within group (order by v.active_seconds))::numeric) as median_seconds_on_page,
        round(avg(v.scroll_pct))                                  as avg_scroll_pct
    from {{ ref('stg_page_views') }} v
    join {{ source('store', 'products') }} p
      on v.path = '/product/' || p.slug
    where v.has_duration
    group by p.id
),
sold as (
    select
        i.product_id,
        sum(i.qty)                 as units_sold,
        sum(i.revenue_cents)       as revenue_cents,
        sum(i.margin_cents)        as margin_cents,
        count(distinct i.order_id) as orders
    from {{ ref('stg_order_items') }} i
    join {{ ref('stg_orders') }} o on o.order_id = i.order_id and o.is_revenue
    group by i.product_id
)
select
    coalesce(pp.product_id, s.product_id)         as product_id,
    pp.product_name,
    pp.category,
    pp.slug,
    coalesce(pp.views, 0)                          as views,
    coalesce(pp.card_clicks, 0)                    as card_clicks,
    coalesce(pp.config_changes, 0)                 as config_changes,
    coalesce(pp.cart_adds, 0)                      as cart_adds,
    coalesce(pp.wishlist_adds, 0)                  as wishlist_adds,
    coalesce(pp.cart_removals, 0)                  as cart_removals,
    coalesce(pp.viewing_sessions, 0)               as viewing_sessions,
    coalesce(pp.adding_sessions, 0)                as adding_sessions,
    coalesce(pp.saving_sessions, 0)                as saving_sessions,
    coalesce(d.avg_seconds_on_page, 0)             as avg_seconds_on_page,
    coalesce(d.median_seconds_on_page, 0)          as median_seconds_on_page,
    coalesce(d.avg_scroll_pct, 0)                  as avg_scroll_pct,
    coalesce(s.units_sold, 0)                      as units_sold,
    coalesce(s.revenue_cents, 0)                   as revenue_cents,
    coalesce(s.margin_cents, 0)                    as margin_cents,
    coalesce(s.orders, 0)                          as orders,
    pp.last_seen_at
from per_product pp
full outer join sold s on s.product_id = pp.product_id
left join dwell d on d.product_id = coalesce(pp.product_id, s.product_id)
