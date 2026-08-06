-- migrate:up

-- Shared helpers. SECURITY DEFINER where a low-privilege role must trip a
-- trigger that writes somewhere it cannot reach itself (audit, ledger).
-- search_path is pinned on every definer function: an unpinned one is a
-- privilege-escalation hole.
create function ops.set_updated_at() returns trigger
  language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

create table store.categories (
  key         text primary key,
  label       text not null,
  tagline     text not null,
  position    int  not null default 0,
  content     jsonb not null default '{}',   -- hero/collections/story copy, was CATEGORY_CONTENT
  archived_at timestamptz
);

create table store.products (
  id          bigint generated always as identity primary key,
  public_id   uuid   not null default gen_random_uuid(),
  -- The "p01" ids from data/products.json. Kept so the JSON fallback and the
  -- Postgres path return byte-identical dicts during the cutover.
  legacy_id   text,
  slug        citext not null,
  name        text   not null check (length(name) between 1 and 200),
  brand       text,
  series      text,
  category    text   not null references store.categories(key),
  color       text,
  short_desc  text,
  description text,
  base_price_cents bigint not null default 0 check (base_price_cents >= 0),
  status      product_status not null default 'draft',
  featured    boolean not null default false,
  position    int     not null default 0,
  specs       jsonb   not null default '{}',
  search_tsv  tsvector generated always as (
                to_tsvector('english',
                  coalesce(name, '') || ' ' || coalesce(brand, '') || ' ' || coalesce(short_desc, ''))
              ) stored,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  archived_at timestamptz
);
create unique index products_public_id on store.products (public_id);
-- Partial unique: a slug is free again only once the old product is archived.
create unique index products_slug_live on store.products (slug) where archived_at is null;
create index products_browse on store.products (category, status, position) where archived_at is null;
create index products_search on store.products using gin (search_tsv);
create index products_name_trgm on store.products using gin (name gin_trgm_ops);
create trigger t_products_updated before update on store.products
  for each row execute function ops.set_updated_at();

create table store.product_images (
  id          bigint generated always as identity primary key,
  product_id  bigint not null references store.products(id) on delete cascade,
  role        text   not null check (role in ('poster', 'gallery', 'frame360', 'customer_photo')),
  url         text   not null,
  alt         text,
  position    int    not null default 0
);
create index product_images_lookup on store.product_images (product_id, role, position);

create table store.product_tags (
  product_id bigint not null references store.products(id) on delete cascade,
  tag        citext not null,
  -- Tag order is author-chosen and reaches the DOM via data-tags, which shop.js
  -- filters on. Alphabetising it would be a silent content change.
  position   int not null default 0,
  primary key (product_id, tag)
);
create index product_tags_by_tag on store.product_tags (tag);

create table store.product_reviews (
  id         bigint generated always as identity primary key,
  product_id bigint not null references store.products(id) on delete cascade,
  name       text   not null,
  rating     int    not null check (rating between 1 and 5),
  body       text   not null,
  approved   boolean not null default true,
  created_at timestamptz not null default now()
);
create index reviews_by_product on store.product_reviews (product_id) where approved;

create table store.variants (
  id               bigint generated always as identity primary key,
  product_id       bigint not null references store.products(id) on delete restrict,
  sku              text   not null,
  barcode          text,
  frame            text   not null,                       -- black|walnut|white|gold
  size             text   not null,                       -- A4|A3|12x18|18x24
  orientation      text   not null default 'portrait',
  finish           text,
  price_cents      bigint not null check (price_cents >= 0),
  sale_price_cents bigint check (sale_price_cents >= 0 and sale_price_cents <= price_cents),
  status           product_status not null default 'active',
  position         int    not null default 0,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  archived_at      timestamptz
);
-- NOTE: a table-level UNIQUE constraint cannot contain an expression, so the
-- (…, coalesce(finish,'')) combo uniqueness is a unique index instead.
create unique index variants_combo on store.variants
  (product_id, frame, size, orientation, coalesce(finish, ''));
create unique index variants_sku_live on store.variants (sku) where archived_at is null;
create index variants_by_product on store.variants (product_id, position);
create index variants_sku_trgm on store.variants using gin (sku gin_trgm_ops);
create trigger t_variants_updated before update on store.variants
  for each row execute function ops.set_updated_at();

-- Poster treatment is an option on the line item, not a variant axis (4 frames
-- x 4 sizes = 16 variants per product; themes would make 48 rows for one
-- surcharge). Priced from this table so admins can change it without a deploy.
create table store.poster_themes (
  key          text primary key,
  label        text not null,
  add_cents    bigint not null default 0 check (add_cents >= 0),
  position     int not null default 0,
  archived_at  timestamptz
);

grant select on store.categories, store.products, store.product_images, store.product_tags,
                store.product_reviews, store.variants, store.poster_themes to store_app;

-- migrate:down
drop table if exists store.poster_themes;
drop table if exists store.variants;
drop table if exists store.product_reviews;
drop table if exists store.product_tags;
drop table if exists store.product_images;
drop table if exists store.products;
drop table if exists store.categories;
drop function if exists ops.set_updated_at();
