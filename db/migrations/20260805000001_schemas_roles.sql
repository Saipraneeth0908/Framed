-- migrate:up

-- Extensions -----------------------------------------------------------------
create extension if not exists citext;      -- case-insensitive slug / email
create extension if not exists pg_trgm;     -- fuzzy admin search on SKU / email
create extension if not exists btree_gin;   -- composite GIN for event props

-- Schemas: separation of concerns is enforced by grants, not by convention. ---
create schema if not exists store;   -- OLTP the storefront touches
create schema if not exists ops;     -- admin-only
create schema if not exists raw;     -- append-only landing zone
create schema if not exists stg;     -- cleaned/typed (dbt)
create schema if not exists mart;    -- analytics tables/matviews the BI layer reads (dbt)
create schema if not exists meta;    -- pipeline runs, watermarks, data-quality results

comment on schema store is 'OLTP: catalog reads, carts, orders, customers';
comment on schema ops   is 'Admin-only: users, audit, settings, components, inventory, production';
comment on schema raw   is 'Append-only landing zone. Partitioned. Never contains customer PII.';
comment on schema mart  is 'Analytics marts. Only schema granted to bi_reader.';

-- Roles ----------------------------------------------------------------------
-- Dev passwords below. Production MUST rotate them out of band:
--   ALTER ROLE store_app PASSWORD '...';   (see deploy/README.md)
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'store_app') then
    create role store_app login password 'store_app_dev';
  end if;
  if not exists (select 1 from pg_roles where rolname = 'admin_app') then
    create role admin_app login password 'admin_app_dev';
  end if;
  if not exists (select 1 from pg_roles where rolname = 'ingest') then
    create role ingest login password 'ingest_dev';
  end if;
  if not exists (select 1 from pg_roles where rolname = 'etl') then
    create role etl login password 'etl_dev';
  end if;
  if not exists (select 1 from pg_roles where rolname = 'bi_reader') then
    create role bi_reader login password 'bi_reader_dev';
  end if;
end $$;

-- Deny by default: nobody gets anything from PUBLIC.
revoke all on schema public from public;
revoke all on database framedobsessions from public;
grant connect on database framedobsessions to store_app, admin_app, ingest, etl, bi_reader;

grant usage on schema store to store_app, admin_app, etl;
grant usage on schema ops   to admin_app, etl;
-- store_app gets USAGE on raw for exactly one table: raw.outbox (granted in
-- migration 007). The outbox is the storefront's only cross-boundary write.
grant usage on schema raw   to ingest, etl, admin_app, store_app;
grant usage on schema stg   to etl;
grant usage on schema mart  to etl, admin_app, bi_reader;
grant usage on schema meta  to etl, admin_app;

grant create on schema stg, mart, meta to etl;   -- dbt materialises here

-- The storefront can never see ops. This is the whole point of the split:
-- a SQL-injection hole in web/ cannot read ops.users, ops.audit_log or PII.
revoke all on schema ops from store_app;

-- BI is read-only and mart-only, now and for every future dbt model.
alter default privileges in schema mart grant select on tables to bi_reader;
alter default privileges for role etl in schema mart grant select on tables to bi_reader, admin_app;
alter default privileges for role etl in schema meta grant select on tables to admin_app;
alter role bi_reader set default_transaction_read_only = on;
alter role bi_reader set statement_timeout = '60s';
alter role store_app set statement_timeout = '10s';
alter role ingest    set statement_timeout = '10s';

-- migrate:down
drop schema if exists meta cascade;
drop schema if exists mart cascade;
drop schema if exists stg cascade;
drop schema if exists raw cascade;
drop schema if exists ops cascade;
drop schema if exists store cascade;

-- DROP ROLE refuses while anything still references the role -- including the
-- CONNECT grant on the database and the default privileges above. DROP OWNED BY
-- clears both in one statement; plain REVOKEs miss at least one every time.
do $$
declare r text;
begin
  foreach r in array array['bi_reader', 'etl', 'ingest', 'admin_app', 'store_app'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('drop owned by %I', r);
      execute format('drop role %I', r);
    end if;
  end loop;
end $$;
