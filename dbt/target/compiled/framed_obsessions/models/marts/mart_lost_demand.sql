
-- Demand we could not serve. Two kinds, deliberately in one table so the owner
-- reads one list rather than remembering to check two.
with zero_results as (
    select
        lower(props ->> 'term')  as signal,
        'zero_result_search'     as kind,
        count(*)                 as occurrences,
        max(occurred_at)         as last_seen
    from "framedobsessions"."stg"."stg_events"
    where event_name = 'search_zero_results' and nullif(props ->> 'term', '') is not null
    group by 1
),
unbuildable_views as (
    select
        p.name                     as signal,
        'viewed_while_unbuildable' as kind,
        count(*)                   as occurrences,
        max(e.occurred_at)         as last_seen
    from "framedobsessions"."stg"."stg_events" e
    join "framedobsessions"."store"."products" p on p.id = e.product_id
    where e.event_name = 'product_view'
      and not exists (
          select 1
          from "framedobsessions"."store"."variants" v
          join "framedobsessions"."ops"."variant_components" vc on vc.variant_id = v.id
          join "framedobsessions"."ops"."components" c on c.id = vc.component_id
          where v.product_id = p.id and (c.on_hand - c.reserved) >= vc.qty
      )
    group by 1
)
select * from zero_results
union all
select * from unbuildable_views