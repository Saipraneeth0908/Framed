
-- Days of cover, not just a threshold: a slow-moving component at 3 units is
-- fine and a fast-moving one at 30 is an emergency. The threshold cannot tell
-- the difference; this can.
with burn as (
    select
        component_id,
        sum(-delta) filter (where reason = 'consume') as consumed_30d
    from "framedobsessions"."stg"."stg_ledger"
    where created_at > now() - interval '30 days'
    group by 1
)
select
    c.id                   as component_id,
    c.sku,
    c.kind,
    c.on_hand,
    c.reserved,
    c.on_hand - c.reserved as available,
    c.low_threshold,
    c.lead_days,
    coalesce(b.consumed_30d, 0)                  as consumed_30d,
    round(coalesce(b.consumed_30d, 0) / 30.0, 2) as daily_burn,
    case when coalesce(b.consumed_30d, 0) > 0
         then round((c.on_hand - c.reserved) / (b.consumed_30d / 30.0), 1)
    end as days_of_cover
from "framedobsessions"."ops"."components" c
left join burn b on b.component_id = c.id
where c.archived_at is null