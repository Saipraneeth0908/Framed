-- migrate:up

create table ops.users (
  id              bigint generated always as identity primary key,
  public_id       uuid   not null default gen_random_uuid(),
  email           citext not null,
  name            text   not null,
  password_hash   text   not null,          -- argon2id
  role            admin_role not null default 'fulfilment',
  totp_secret_enc text,                     -- Fernet ciphertext, key never in the DB
  totp_enabled    boolean not null default false,
  -- Bumping this invalidates every live session for the user. Password change
  -- and role change both bump it; the session check compares on each request.
  session_version int    not null default 1,
  failed_attempts int    not null default 0,
  locked_until    timestamptz,
  last_login_at   timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  archived_at     timestamptz
);
create unique index users_email_live on ops.users (email) where archived_at is null;
create index users_email_trgm on ops.users using gin ((email::text) gin_trgm_ops);
create trigger t_users_updated before update on ops.users
  for each row execute function ops.set_updated_at();

create table ops.password_resets (
  id         bigint generated always as identity primary key,
  user_id    bigint not null references ops.users(id) on delete cascade,
  token_hash bytea  not null,               -- sha256 of the emailed token; never the token
  expires_at timestamptz not null,
  used_at    timestamptz,
  created_at timestamptz not null default now()
);
create unique index password_resets_token on ops.password_resets (token_hash);

-- Append-only. Written by trigger only; no app code path can skip it.
create table ops.audit_log (
  id         bigint generated always as identity primary key,
  actor_id   bigint references ops.users(id),
  action     text not null,
  entity     text not null,
  entity_id  bigint,
  before     jsonb,
  after      jsonb,
  request_id text,
  created_at timestamptz not null default now()
);
create index audit_entity on ops.audit_log (entity, entity_id, created_at desc);
create index audit_actor  on ops.audit_log (actor_id, created_at desc);
create index audit_time   on ops.audit_log (created_at desc);

create table ops.settings (
  key        text primary key,
  value      jsonb not null,
  updated_by bigint references ops.users(id),
  updated_at timestamptz not null default now()
);

-- The unbypassable audit trigger. Actor comes from a per-transaction GUC set by
-- the request wrapper (SET LOCAL app.actor_id), so forgetting to log is not
-- possible from application code -- only forgetting to set the actor, which
-- degrades to a NULL actor on a row that still exists.
create function ops.audit() returns trigger
  language plpgsql
  security definer
  set search_path = ops, pg_catalog
as $$
begin
  insert into ops.audit_log (actor_id, action, entity, entity_id, before, after, request_id)
  values (
    nullif(current_setting('app.actor_id', true), '')::bigint,
    lower(tg_op),
    tg_table_schema || '.' || tg_table_name,
    case when tg_op = 'DELETE' then (to_jsonb(old) ->> 'id')::bigint
         else (to_jsonb(new) ->> 'id')::bigint end,
    case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) end,
    case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) end,
    nullif(current_setting('app.request_id', true), '')
  );
  return coalesce(new, old);
end $$;

-- Convenience so a table only ever gets audited one way.
create function ops.attach_audit(target regclass) returns void
  language plpgsql as $$
begin
  execute format(
    'create trigger t_audit after insert or update or delete on %s
       for each row execute function ops.audit()', target);
end $$;

select ops.attach_audit('store.products');
select ops.attach_audit('store.variants');
select ops.attach_audit('store.categories');
select ops.attach_audit('store.poster_themes');
select ops.attach_audit('ops.users');
select ops.attach_audit('ops.settings');

grant select, insert, update on ops.users, ops.settings, ops.password_resets to admin_app;
grant select on ops.audit_log to admin_app;
grant usage, select on all sequences in schema ops to admin_app;

-- migrate:down
drop function if exists ops.attach_audit(regclass);
drop function if exists ops.audit() cascade;
drop table if exists ops.settings;
drop table if exists ops.audit_log;
drop table if exists ops.password_resets;
drop table if exists ops.users;
