select
    l.id            as ledger_id,
    l.component_id,
    c.sku           as component_sku,
    c.kind          as component_kind,
    l.delta,
    l.reserved_delta,
    l.reason::text  as reason,
    l.order_item_id,
    l.created_at,
    l.created_at::date as movement_date
from {{ source('ops', 'inventory_ledger') }} l
join {{ source('ops', 'components') }} c on c.id = l.component_id
