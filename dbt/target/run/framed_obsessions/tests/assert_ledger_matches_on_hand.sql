
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- The single most important invariant in the system: the cached balance on
-- ops.components must equal the sum of the append-only ledger. If this returns
-- rows, every stock number the owner sees is a lie.
select
    c.id as component_id,
    c.sku,
    c.on_hand  as cached_on_hand,
    coalesce(sum(l.delta), 0)          as ledger_on_hand,
    c.reserved as cached_reserved,
    coalesce(sum(l.reserved_delta), 0) as ledger_reserved
from "framedobsessions"."ops"."components" c
left join "framedobsessions"."ops"."inventory_ledger" l on l.component_id = c.id
group by c.id, c.sku, c.on_hand, c.reserved
having c.on_hand  <> coalesce(sum(l.delta), 0)
    or c.reserved <> coalesce(sum(l.reserved_delta), 0)
  
  
      
    ) dbt_internal_test