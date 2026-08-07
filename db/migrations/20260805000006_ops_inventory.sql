-- migrate:up

-- Stock is tracked per COMPONENT (blank frames, paper, glass), not per finished
-- SKU. 11 products x 16 variants = 176 SKUs but only ~12 real things on a shelf.
create table ops.components (
  id              bigint generated always as identity primary key,
  sku             text not null unique,
  name            text not null,
  kind            text not null check (kind in ('frame', 'paper', 'mount', 'glass', 'packaging', 'other')),
  attrs           jsonb not null default '{}',      -- {size:"A3", finish:"walnut"}
  on_hand         int  not null default 0,
  reserved        int  not null default 0,
  low_threshold   int  not null default 5,
  unit_cost_cents bigint not null default 0 check (unit_cost_cents >= 0),
  supplier        text,
  lead_days       int,
  archived_at     timestamptz,
  -- The entire inventory design lives on this line: overselling becomes a
  -- database error, not a logic bug you hope you caught in review.
  constraint stock_sane check (on_hand >= 0 and reserved >= 0 and reserved <= on_hand)
);
-- Not named components_low: indexes and views share one relation namespace in
-- Postgres, and ops.components_low (the view) is created below.
create index components_by_kind on ops.components (kind) where archived_at is null;

create table ops.variant_components (        -- bill of materials
  variant_id   bigint not null references store.variants(id) on delete cascade,
  component_id bigint not null references ops.components(id) on delete restrict,
  qty          int    not null check (qty > 0),
  primary key (variant_id, component_id)
);
create index bom_by_component on ops.variant_components (component_id);

-- Append-only source of truth. components.on_hand/reserved are caches the
-- trigger maintains; the nightly drift check asserts they still agree.
create table ops.inventory_ledger (
  id             bigint generated always as identity primary key,
  component_id   bigint not null references ops.components(id) on delete restrict,
  delta          int    not null default 0,   -- change to on_hand
  reserved_delta int    not null default 0,   -- change to reserved
  reason         adj_reason not null,
  order_item_id  bigint references store.order_items(id),
  actor_id       bigint references ops.users(id),
  note           text,
  created_at     timestamptz not null default now(),
  constraint ledger_moves_something check (delta <> 0 or reserved_delta <> 0)
);
create index ledger_component_time on ops.inventory_ledger (component_id, created_at desc);
create index ledger_order_item on ops.inventory_ledger (order_item_id) where order_item_id is not null;

create function ops.apply_ledger() returns trigger
  language plpgsql
  security definer
  set search_path = ops, pg_catalog
as $$
begin
  update ops.components
     set on_hand  = on_hand  + new.delta,
         reserved = reserved + new.reserved_delta
   where id = new.component_id;
  return new;
end $$;
create trigger t_apply_ledger after insert on ops.inventory_ledger
  for each row execute function ops.apply_ledger();

-- Ledger rows are never edited. Corrections are new rows with reason
-- 'correction' -- that is what makes the append-only claim true.
create function ops.ledger_is_append_only() returns trigger
  language plpgsql as $$
begin
  raise exception 'ops.inventory_ledger is append-only; insert a correcting row instead'
    using errcode = 'restrict_violation';
end $$;
create trigger t_ledger_append_only before update or delete on ops.inventory_ledger
  for each row execute function ops.ledger_is_append_only();

-- Nightly job calls this; non-empty result pages someone.
create function ops.ledger_drift()
  returns table (component_id bigint, sku text, cached_on_hand int, ledger_on_hand bigint,
                 cached_reserved int, ledger_reserved bigint)
  language sql stable as $$
  select c.id, c.sku, c.on_hand, coalesce(sum(l.delta), 0),
         c.reserved, coalesce(sum(l.reserved_delta), 0)
    from ops.components c
    left join ops.inventory_ledger l on l.component_id = c.id
   group by c.id, c.sku, c.on_hand, c.reserved
  having c.on_hand <> coalesce(sum(l.delta), 0)
      or c.reserved <> coalesce(sum(l.reserved_delta), 0);
$$;

-- What a variant needs, and how many of it we could build right now.
create view ops.variant_buildable as
  select v.id as variant_id, v.sku,
         min((c.on_hand - c.reserved) / vc.qty) as buildable
    from store.variants v
    join ops.variant_components vc on vc.variant_id = v.id
    join ops.components c on c.id = vc.component_id
   group by v.id, v.sku;

create view ops.components_low as
  select * from ops.components
   where archived_at is null and (on_hand - reserved) <= low_threshold;

select ops.attach_audit('ops.components');
select ops.attach_audit('ops.variant_components');

grant select, insert, update on ops.components, ops.variant_components to admin_app;
grant select, insert on ops.inventory_ledger to admin_app;
grant select on ops.variant_buildable, ops.components_low to admin_app;
grant usage, select on all sequences in schema ops to admin_app;
-- The storefront reserves stock at checkout. It writes the ledger and nothing
-- else in ops; the trigger (SECURITY DEFINER) updates the cache on its behalf.
grant insert, select on ops.inventory_ledger to store_app;
grant usage on schema ops to store_app;
grant select on ops.components, ops.variant_components, ops.variant_buildable to store_app;
grant usage, select on sequence ops.inventory_ledger_id_seq to store_app;
grant select on all tables in schema ops to etl;

-- migrate:down
drop view if exists ops.components_low;
drop view if exists ops.variant_buildable;
drop function if exists ops.ledger_drift();
drop trigger if exists t_ledger_append_only on ops.inventory_ledger;
drop function if exists ops.ledger_is_append_only();
drop trigger if exists t_apply_ledger on ops.inventory_ledger;
drop function if exists ops.apply_ledger();
drop table if exists ops.inventory_ledger;
drop table if exists ops.variant_components;
drop table if exists ops.components;
