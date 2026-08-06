-- migrate:up

create table store.customers (
  id            bigint generated always as identity primary key,
  public_id     uuid   not null default gen_random_uuid(),
  email         citext not null,
  name          text,
  phone         text,
  marketing_opt_in boolean not null default false,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  archived_at   timestamptz
);
create unique index customers_email_live on store.customers (email) where archived_at is null;
create index customers_email_trgm on store.customers using gin ((email::text) gin_trgm_ops);
create trigger t_customers_updated before update on store.customers
  for each row execute function ops.set_updated_at();

-- Server-side carts. The browser cookie holds only the public_id token, so cart
-- contents and prices can never be tampered with client-side.
create table store.carts (
  id               bigint generated always as identity primary key,
  public_id        uuid not null default gen_random_uuid(),
  customer_id      bigint references store.customers(id) on delete set null,
  email            citext,
  state            cart_state not null default 'active',
  currency         char(3) not null default 'USD',
  discount_code    text,
  session_id       uuid,
  created_at       timestamptz not null default now(),
  last_activity_at timestamptz not null default now(),
  converted_at     timestamptz,
  abandoned_at     timestamptz
);
create unique index carts_public_id on store.carts (public_id);
create index carts_sweep on store.carts (state, last_activity_at) where state = 'active';

create table store.cart_items (
  id           bigint generated always as identity primary key,
  cart_id      bigint not null references store.carts(id) on delete cascade,
  variant_id   bigint not null references store.variants(id) on delete restrict,
  poster_theme text   not null default 'racing_stripes' references store.poster_themes(key),
  qty          int    not null check (qty > 0 and qty <= 25),
  -- Price is re-derived from the catalog on read; this column is the price the
  -- customer was last shown, used to flag "price changed since you added this".
  unit_price_cents bigint not null check (unit_price_cents >= 0),
  added_at     timestamptz not null default now(),
  constraint cart_line_unique unique (cart_id, variant_id, poster_theme)
);
create index cart_items_by_cart on store.cart_items (cart_id);

-- Human-speakable order number: FO-2026-000042
create sequence store.order_no_seq;
create function store.next_order_no() returns text
  language sql as $$
  select 'FO-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('store.order_no_seq')::text, 6, '0');
$$;

create table store.orders (
  id                bigint generated always as identity primary key,
  public_id         uuid not null default gen_random_uuid(),
  order_no          text not null default store.next_order_no(),
  customer_id       bigint references store.customers(id) on delete restrict,
  cart_id           bigint references store.carts(id) on delete set null,
  email             citext not null,
  phone             text,

  payment_status    payment_status not null default 'unpaid',
  fulfilment_status fulfil_status  not null default 'unfulfilled',
  -- Rollup of the least-advanced non-cancelled line item. Maintained by
  -- trigger, never hand-set: three independent axes, one derived summary.
  production_rollup prod_status,

  currency          char(3) not null default 'USD',
  subtotal_cents    bigint not null default 0 check (subtotal_cents >= 0),
  discount_cents    bigint not null default 0 check (discount_cents >= 0),
  shipping_cents    bigint not null default 0 check (shipping_cents >= 0),
  tax_cents         bigint not null default 0 check (tax_cents >= 0),
  total_cents       bigint not null default 0 check (total_cents >= 0),
  refunded_cents    bigint not null default 0 check (refunded_cents >= 0),
  discount_code     text,

  ship_name         text, ship_street text, ship_unit text, ship_city text,
  ship_state        text, ship_zip text, ship_country text, ship_instructions text,

  stripe_payment_intent text,
  placed_at         timestamptz not null default now(),
  paid_at           timestamptz,
  cancelled_at      timestamptz,
  cancel_reason     text,
  internal_note     text,
  updated_at        timestamptz not null default now()
);
create unique index orders_public_id on store.orders (public_id);
create unique index orders_order_no  on store.orders (order_no);
create unique index orders_intent    on store.orders (stripe_payment_intent)
  where stripe_payment_intent is not null;
create index orders_list  on store.orders (placed_at desc);
create index orders_state on store.orders (payment_status, fulfilment_status, placed_at desc);
create index orders_email on store.orders (email, placed_at desc);
create trigger t_orders_updated before update on store.orders
  for each row execute function ops.set_updated_at();

create table store.order_items (
  id                bigint generated always as identity primary key,
  order_id          bigint not null references store.orders(id) on delete restrict,
  variant_id        bigint references store.variants(id) on delete set null,
  product_id        bigint references store.products(id) on delete set null,
  -- Snapshots. Reports must not shift when someone renames a product in March.
  sku_snapshot      text  not null,
  name_snapshot     text  not null,
  attrs_snapshot    jsonb not null,
  qty               int   not null check (qty > 0),
  unit_price_cents  bigint not null check (unit_price_cents >= 0),
  discount_cents    bigint not null default 0 check (discount_cents >= 0),
  cost_cents        bigint not null default 0,   -- summed BOM at purchase -> real margin
  production_status prod_status not null default 'queued',
  blocked_reason    text,
  station_started_at timestamptz,
  packed_at         timestamptz,
  refunded_qty      int not null default 0 check (refunded_qty >= 0 and refunded_qty <= qty)
);
create index oi_by_order on store.order_items (order_id);
create index oi_by_variant on store.order_items (variant_id);
-- Powers the production board: only unfinished work is indexed.
create index oi_board on store.order_items (production_status, station_started_at)
  where production_status not in ('packed', 'cancelled');

create table store.refunds (
  id            bigint generated always as identity primary key,
  order_id      bigint not null references store.orders(id) on delete restrict,
  order_item_id bigint references store.order_items(id) on delete restrict,
  amount_cents  bigint not null check (amount_cents > 0),
  qty           int,
  reason        text not null,
  restocked     boolean not null default false,
  stripe_refund_id text,
  actor_id      bigint references ops.users(id),
  created_at    timestamptz not null default now()
);
create index refunds_by_order on store.refunds (order_id, created_at desc);

create table store.shipments (
  id            bigint generated always as identity primary key,
  order_id      bigint not null references store.orders(id) on delete restrict,
  carrier       text,
  tracking_no   text,
  tracking_url  text,
  shipped_at    timestamptz not null default now(),
  delivered_at  timestamptz,
  actor_id      bigint references ops.users(id)
);
create index shipments_by_order on store.shipments (order_id);

create table store.discounts (
  id             bigint generated always as identity primary key,
  code           citext not null,
  kind           discount_kind not null,
  value          bigint not null check (value >= 0),   -- percent points, or cents
  min_subtotal_cents bigint not null default 0,
  starts_at      timestamptz,
  ends_at        timestamptz,
  max_redemptions int,
  redemptions    int not null default 0,
  active         boolean not null default true,
  created_at     timestamptz not null default now(),
  archived_at    timestamptz,
  check (kind <> 'percent' or value <= 100)
);
create unique index discounts_code_live on store.discounts (code) where archived_at is null;

-- History is frozen once money has moved. Production and fulfilment columns
-- stay mutable -- freezing those would break the workshop board.
create function store.freeze_order_items() returns trigger
  language plpgsql as $$
declare
  pay payment_status;
begin
  select o.payment_status into pay from store.orders o
    where o.id = coalesce(old.order_id, new.order_id);
  if pay = 'unpaid' then
    return coalesce(new, old);
  end if;

  if tg_op = 'DELETE' then
    raise exception 'order_items are immutable once paid (order %); issue a refund instead', old.order_id
      using errcode = 'restrict_violation';
  end if;

  if (new.qty, new.unit_price_cents, new.sku_snapshot, new.name_snapshot,
      new.attrs_snapshot, new.cost_cents, new.order_id, new.discount_cents)
     is distinct from
     (old.qty, old.unit_price_cents, old.sku_snapshot, old.name_snapshot,
      old.attrs_snapshot, old.cost_cents, old.order_id, old.discount_cents) then
    raise exception 'financial fields of order_items are frozen once paid (order %); issue a refund instead', old.order_id
      using errcode = 'restrict_violation';
  end if;
  return new;
end $$;
create trigger t_freeze_order_items before update or delete on store.order_items
  for each row execute function store.freeze_order_items();

-- Least-advanced non-cancelled item wins. min() works on enums via their
-- declaration order, which is exactly the workshop station order.
-- SECURITY DEFINER: production_rollup is a derived column the database
-- maintains, not an application write. store_app has INSERT on orders but
-- deliberately no UPDATE, and it must still be able to insert order_items.
create function store.roll_up_production() returns trigger
  language plpgsql
  security definer
  set search_path = store, pg_catalog
as $$
declare
  oid bigint := coalesce(new.order_id, old.order_id);
begin
  update store.orders o
     set production_rollup = (
           select min(i.production_status) from store.order_items i
            where i.order_id = oid and i.production_status <> 'cancelled')
   where o.id = oid;
  return coalesce(new, old);
end $$;
create trigger t_rollup_production after insert or update of production_status or delete
  on store.order_items for each row execute function store.roll_up_production();

select ops.attach_audit('store.orders');
select ops.attach_audit('store.order_items');
select ops.attach_audit('store.refunds');
select ops.attach_audit('store.discounts');
select ops.attach_audit('store.shipments');

-- Storefront: full access to its own carts, insert-only on orders, read on
-- discounts. It cannot mutate an order after checkout hands off.
grant select, insert, update, delete on store.carts, store.cart_items to store_app;
grant select, insert, update on store.customers to store_app;
grant select, insert on store.orders, store.order_items to store_app;
-- Column-level UPDATE: the payment webhook settles an order from the storefront
-- process, but store_app still cannot touch totals, addresses or fulfilment.
grant update (payment_status, paid_at, stripe_payment_intent) on store.orders to store_app;
grant select on store.discounts to store_app;
grant usage, select on all sequences in schema store to store_app;

grant select, insert, update, delete on all tables in schema store to admin_app;
grant usage, select on all sequences in schema store to admin_app;
grant select on all tables in schema store to etl;

-- migrate:down
drop trigger if exists t_rollup_production on store.order_items;
drop function if exists store.roll_up_production();
drop trigger if exists t_freeze_order_items on store.order_items;
drop function if exists store.freeze_order_items();
drop table if exists store.discounts;
drop table if exists store.shipments;
drop table if exists store.refunds;
drop table if exists store.order_items;
drop table if exists store.orders;
drop function if exists store.next_order_no();
drop sequence if exists store.order_no_seq;
drop table if exists store.cart_items;
drop table if exists store.carts;
drop table if exists store.customers;
