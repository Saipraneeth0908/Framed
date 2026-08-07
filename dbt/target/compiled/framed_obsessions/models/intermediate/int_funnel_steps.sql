-- One row per session with the furthest step it reached.
--
-- Steps are made cumulative here rather than read literally off the events: a
-- session that purchased self-evidently reached checkout, even when the client
-- never emitted checkout_start. Adding to cart straight from a listing card
-- does exactly that -- there is no product_view to emit.
--
-- Without this the funnel reports more purchases than checkouts and every
-- conversion rate downstream is nonsense. With it, assert_funnel_is_monotonic
-- tests something real (a sessionization bug) rather than restating whatever
-- the browser happened to send.
select
    session_key,
    started_at::date as day,
    device,
    utm_source,
    country,
    1 as reached_view,
    case when saw_product or added_to_cart or started_checkout or purchased
         then 1 else 0 end as reached_product,
    case when added_to_cart or started_checkout or purchased
         then 1 else 0 end as reached_cart,
    case when started_checkout or purchased
         then 1 else 0 end as reached_checkout,
    case when purchased
         then 1 else 0 end as reached_purchase
from "framedobsessions"."stg"."stg_sessions"