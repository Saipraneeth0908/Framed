-- migrate:up

create table raw.events (
  event_id      uuid        not null,        -- client-generated -> idempotent retries
  occurred_at   timestamptz not null,
  received_at   timestamptz not null default now(),
  session_id    uuid        not null,
  visitor_hash  bytea       not null,        -- rotating salted hash, never an IP
  name          text        not null,
  path          text,
  product_id    bigint,
  variant_id    bigint,
  cart_id       bigint,
  device        text, browser text, os text, country char(2),
  referrer_host text,
  utm           jsonb,
  props         jsonb not null default '{}',
  primary key (event_id, occurred_at)        -- partition key must be in the PK
) partition by range (occurred_at);

create index events_name_time on raw.events (name, occurred_at desc);
create index events_session   on raw.events (session_id, occurred_at);
create index events_product   on raw.events (product_id, occurred_at) where product_id is not null;
create index events_props     on raw.events using gin (props);
-- BRIN costs kilobytes and makes the range scans dbt does every hour cheap.
create index events_brin      on raw.events using brin (occurred_at);

-- Monthly partitions. pg_partman is not in postgres:16-alpine and this is 20
-- lines; swap to pg_partman when partition count or retention rules grow.
create function raw.ensure_event_partitions(months_ahead int default 3) returns int
  language plpgsql as $$
declare
  m date := date_trunc('month', now())::date;
  i int;
  made int := 0;
  part text;
begin
  for i in 0..months_ahead loop
    part := 'events_' || to_char(m + (i || ' months')::interval, 'YYYYMM');
    if not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'raw' and c.relname = part) then
      execute format(
        'create table raw.%I partition of raw.events for values from (%L) to (%L)',
        part,
        (m + (i || ' months')::interval)::date,
        (m + ((i + 1) || ' months')::interval)::date);
      execute format('grant insert, select on raw.%I to ingest', part);
      execute format('grant select on raw.%I to etl', part);
      made := made + 1;
    end if;
  end loop;
  return made;
end $$;

-- Retention: raw drops at 25 months, mart aggregates keep forever.
create function raw.drop_old_event_partitions(keep_months int default 25) returns int
  language plpgsql as $$
declare
  r record;
  cutoff date := (date_trunc('month', now()) - (keep_months || ' months')::interval)::date;
  dropped int := 0;
begin
  for r in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'raw' and c.relname ~ '^events_[0-9]{6}$'
  loop
    if to_date(right(r.relname, 6), 'YYYYMM') < cutoff then
      execute format('drop table raw.%I', r.relname);
      dropped := dropped + 1;
    end if;
  end loop;
  return dropped;
end $$;

select raw.ensure_event_partitions(3);

-- Transactional outbox. Written in the SAME transaction as the business fact,
-- so analytics can never disagree with the ledger. Debezium CDC replaces the
-- relay at Tier 3; this table stays, so nothing upstream changes.
create table raw.outbox (
  id           bigint generated always as identity primary key,
  topic        text  not null,
  payload      jsonb not null,
  created_at   timestamptz not null default now(),
  published_at timestamptz
);
create index outbox_unpublished on raw.outbox (id) where published_at is null;

create function raw.notify_outbox() returns trigger
  language plpgsql as $$
begin
  perform pg_notify('outbox', new.id::text);
  return new;
end $$;
create trigger t_notify_outbox after insert on raw.outbox
  for each row execute function raw.notify_outbox();

create table raw.domain_events (
  id          bigint generated always as identity primary key,
  outbox_id   bigint not null unique,
  topic       text  not null,
  payload     jsonb not null,
  occurred_at timestamptz not null,
  relayed_at  timestamptz not null default now()
);
create index domain_events_topic_time on raw.domain_events (topic, occurred_at desc);

create table raw.stripe_txns (
  id          text primary key,              -- Stripe balance transaction id
  type        text,
  amount_cents bigint,
  fee_cents   bigint,
  net_cents   bigint,
  currency    char(3),
  created_at  timestamptz not null,
  payload     jsonb not null,
  loaded_at   timestamptz not null default now()
);
create index stripe_txns_created on raw.stripe_txns (created_at desc);

-- meta: watermarks and quality results, so reruns are idempotent and a failed
-- test pages you before the owner sees a wrong number.
create table meta.ingest_state (
  source     text primary key,
  watermark  timestamptz not null,
  cursor     text,
  updated_at timestamptz not null default now()
);

create table meta.dbt_runs (
  id          bigint generated always as identity primary key,
  invocation_id uuid,
  model       text not null,
  status      text not null,
  rows_affected bigint,
  duration_ms bigint,
  run_at      timestamptz not null default now()
);
create index dbt_runs_time on meta.dbt_runs (run_at desc);

create table meta.dq_results (
  id         bigint generated always as identity primary key,
  test_name  text not null,
  status     text not null check (status in ('pass', 'fail', 'warn', 'error')),
  failures   bigint not null default 0,
  message    text,
  run_at     timestamptz not null default now()
);
create index dq_results_time on meta.dq_results (run_at desc, status);

grant insert, select on raw.events to ingest;
grant select on raw.events, raw.outbox, raw.domain_events, raw.stripe_txns to etl;
grant insert on raw.outbox to store_app, admin_app;
grant usage, select on sequence raw.outbox_id_seq to store_app, admin_app;
grant select, update on raw.outbox to etl;
grant insert, select on raw.domain_events, raw.stripe_txns to etl;
grant usage, select on all sequences in schema raw to etl;
grant select, insert, update, delete on all tables in schema meta to etl;
grant usage, select on all sequences in schema meta to etl;
grant select on all tables in schema meta to admin_app;

-- migrate:down
drop table if exists meta.dq_results;
drop table if exists meta.dbt_runs;
drop table if exists meta.ingest_state;
drop table if exists raw.stripe_txns;
drop table if exists raw.domain_events;
drop trigger if exists t_notify_outbox on raw.outbox;
drop function if exists raw.notify_outbox();
drop table if exists raw.outbox;
drop function if exists raw.drop_old_event_partitions(int);
drop function if exists raw.ensure_event_partitions(int);
drop table if exists raw.events;
