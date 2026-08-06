
  create view "framedobsessions"."stg"."stg_orders__dbt_tmp"
    
    
  as (
    select
    o.id                        as order_id,
    o.order_no,
    o.customer_id,
    o.cart_id,
    o.email,
    o.payment_status::text      as payment_status,
    o.fulfilment_status::text   as fulfilment_status,
    o.subtotal_cents,
    o.discount_cents,
    o.shipping_cents,
    o.tax_cents,
    o.total_cents,
    o.refunded_cents,
    o.total_cents - o.refunded_cents as net_cents,
    o.discount_code,
    o.ship_country,
    o.ship_state,
    o.placed_at,
    o.paid_at,
    o.cancelled_at,
    o.placed_at::date           as placed_date,
    (o.payment_status in ('paid', 'partially_refunded') and o.cancelled_at is null) as is_revenue
from "framedobsessions"."store"."orders" o
  );