

-- Typed, trimmed view of the landing zone. Nothing is filtered out here except
-- rows that cannot be interpreted at all -- deciding what "counts" belongs
-- downstream, where the definition is visible next to the metric.
select
    e.event_id,
    e.occurred_at,
    e.received_at,
    e.session_id,
    encode(e.visitor_hash, 'hex')            as visitor_key,
    e.name                                   as event_name,
    nullif(e.path, '')                       as path,
    e.product_id,
    e.variant_id,
    e.cart_id,
    coalesce(e.device, 'unknown')            as device,
    coalesce(e.browser, 'unknown')           as browser,
    coalesce(e.os, 'unknown')                as os,
    e.country,
    e.referrer_host,
    coalesce(e.utm ->> 'source', 'direct')   as utm_source,
    e.utm ->> 'medium'                       as utm_medium,
    e.utm ->> 'campaign'                     as utm_campaign,
    e.props,
    -- Events carry a version in props so a schema change can be handled here
    -- for one release instead of breaking every downstream model at once.
    coalesce((e.props ->> 'v')::int, 1)      as event_version
from "framedobsessions"."raw"."events" e

where e.occurred_at > (select coalesce(max(occurred_at), '2000-01-01'::timestamptz) from "framedobsessions"."stg"."stg_events")
                      - interval '3 hours'
