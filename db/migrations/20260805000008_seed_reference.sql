-- migrate:up
-- Reference data that used to be Python constants in main.py. Deterministic, so
-- it belongs in a migration; the product catalog itself is seeded from
-- data/products.json by scripts/seed_catalog.py.

insert into store.categories (key, label, tagline, position) values
  ('hotwheels',  'Hot Wheels', 'Die-cast icons, framed for the wall.', 1),
  ('cricket',    'Cricket',    'Legends of the pitch, in frame.',      2),
  ('anime',      'Anime',      'Frame your fandom.',                   3),
  ('nature',     'Nature',     'The wild, on your wall.',              4),
  ('motivation', 'Motivation', 'Fuel for every single day.',           5);

-- Surcharges preserved exactly from compute_config_price() so no displayed
-- price moves during the migration.
insert into store.poster_themes (key, label, add_cents, position) values
  ('racing_stripes', 'Racing stripes', 0,   1),
  ('circuit',        'Circuit',        800, 2),
  ('minimal',        'Minimal',        0,   3);

-- Components: a frame blank is size+finish specific; paper/mount/glass/packaging
-- vary by size only. 4x4 + 4x4 = 32 real things on a shelf.
-- on_hand is left at 0 on insert: the ledger is the source of truth and its
-- trigger sets the balance. Seeding a balance AND a matching ledger row would
-- double-count every component -- exactly the drift ops.ledger_drift() exists
-- to catch.
insert into ops.components (sku, name, kind, attrs, low_threshold, unit_cost_cents, supplier, lead_days)
select
  'FRM-' || upper(replace(s.size, 'x', 'X')) || '-' || upper(left(f.finish, 3)),
  initcap(f.finish) || ' frame ' || s.size,
  'frame',
  jsonb_build_object('size', s.size, 'finish', f.finish),
  8,
  (s.cost * f.mult)::int,
  'Northgate Framing', 14
from (values ('A4', 900), ('A3', 1300), ('12x18', 1500), ('18x24', 2100)) as s(size, cost)
cross join (values ('black', 1.0), ('walnut', 1.55), ('white', 1.2), ('gold', 1.8)) as f(finish, mult);

insert into ops.components (sku, name, kind, attrs, low_threshold, unit_cost_cents, supplier, lead_days)
select 'PPR-' || upper(replace(s.size, 'x', 'X')), 'Giclee paper ' || s.size, 'paper',
       jsonb_build_object('size', s.size), 40, s.cost, 'Hahnemuhle', 10
from (values ('A4', 180), ('A3', 260), ('12x18', 300), ('18x24', 420)) as s(size, cost);

insert into ops.components (sku, name, kind, attrs, low_threshold, unit_cost_cents, supplier, lead_days)
select 'MNT-' || upper(replace(s.size, 'x', 'X')), 'Mount board ' || s.size, 'mount',
       jsonb_build_object('size', s.size), 25, s.cost, 'Northgate Framing', 14
from (values ('A4', 120), ('A3', 170), ('12x18', 200), ('18x24', 280)) as s(size, cost);

insert into ops.components (sku, name, kind, attrs, low_threshold, unit_cost_cents, supplier, lead_days)
select 'GLS-' || upper(replace(s.size, 'x', 'X')), 'Anti-glare glazing ' || s.size, 'glass',
       jsonb_build_object('size', s.size), 15, s.cost, 'ClearView', 21
from (values ('A4', 260), ('A3', 380), ('12x18', 440), ('18x24', 620)) as s(size, cost);

insert into ops.components (sku, name, kind, attrs, low_threshold, unit_cost_cents, supplier, lead_days)
select 'PKG-' || upper(replace(s.size, 'x', 'X')), 'Shipping carton ' || s.size, 'packaging',
       jsonb_build_object('size', s.size), 30, s.cost, 'BoxCo', 7
from (values ('A4', 150), ('A3', 210), ('12x18', 240), ('18x24', 330)) as s(size, cost);

-- Opening balances, applied through the ledger so sum(delta) = on_hand holds
-- from the very first row.
insert into ops.inventory_ledger (component_id, delta, reason, note)
select id,
       case kind when 'frame' then 40 when 'paper' then 250 when 'mount' then 150
                 when 'glass' then 90 when 'packaging' then 200 end,
       'receive', 'Opening balance (migration 008)'
from ops.components;

insert into ops.settings (key, value) values
  ('store.name',            '"Framed Obsessions"'),
  ('store.currency',        '"USD"'),
  ('store.bundle_min_qty',  '3'),
  ('store.bundle_percent',  '10'),
  ('ops.stuck_order_hours', '24'),
  ('ops.low_stock_digest',  'true');

-- migrate:down
-- This migration seeds the reference data everything else hangs off, so its
-- rollback has to take the catalog seeded on top of it (scripts/seed_catalog.py)
-- with it -- otherwise foreign keys block the rollback. Orders are deliberately
-- NOT touched: if real orders exist, this rollback should fail loudly.
delete from ops.settings;
delete from ops.variant_components;
delete from store.cart_items;
delete from store.product_tags;
delete from store.product_images;
delete from store.product_reviews;
delete from store.variants;
delete from store.products;

-- The append-only guard is doing its job here; a rollback is the one legitimate
-- reason to step around it, and only inside this transaction.
alter table ops.inventory_ledger disable trigger t_ledger_append_only;
delete from ops.inventory_ledger;
alter table ops.inventory_ledger enable trigger t_ledger_append_only;

delete from ops.components;
delete from store.poster_themes;
delete from store.categories;
