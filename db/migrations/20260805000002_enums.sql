-- migrate:up
-- Postgres ENUMs make invalid state unrepresentable. ALTER TYPE ADD VALUE is
-- online in PG12+, so adding a state later is not a rewrite.

create type product_status as enum ('draft', 'active', 'archived');

create type payment_status as enum (
  'unpaid', 'authorized', 'paid', 'partially_refunded', 'refunded', 'failed'
);

create type fulfil_status as enum (
  'unfulfilled', 'partially_fulfilled', 'fulfilled', 'in_transit', 'delivered', 'returned'
);

-- Per line item, not per order: one order can have a printed poster and a
-- blocked one at the same time.
create type prod_status as enum (
  'queued', 'blocked', 'printing', 'printed', 'mounting', 'framing',
  'qc', 'reprint', 'packed', 'cancelled'
);

create type adj_reason as enum (
  'receive', 'consume', 'damage', 'return', 'correction', 'cancel_restock', 'reserve', 'unreserve'
);

create type admin_role as enum ('owner', 'manager', 'inventory', 'fulfilment');

create type cart_state as enum ('active', 'converted', 'abandoned', 'expired');

create type discount_kind as enum ('percent', 'fixed', 'free_shipping');

-- migrate:down
drop type if exists discount_kind;
drop type if exists cart_state;
drop type if exists admin_role;
drop type if exists adj_reason;
drop type if exists prod_status;
drop type if exists fulfil_status;
drop type if exists payment_status;
drop type if exists product_status;
