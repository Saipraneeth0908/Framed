# Framed Obsessions — Backlog

Next steps after the rebrand + category theme switcher. Ordered by priority.

## Done
- Rebrand → Framed Obsessions (header, footer, titles, meta, product data).
- Logo everywhere: favicon (`logo-favicon.png`), top bar (`logo-lockup.png`), dark header + footer (white variant `logo-lockup-light.png`).
- Category theme switcher: top-bar dropdown + clickable category icon row, reskins accents, persists in localStorage, filters posters.
- Foundation neutrals set to spec (Obsidian / Warm Ivory / Graphite).
- Per-category accent palette + one signature hero background pattern each.
- Themed section backgrounds (category tint over neutral, no longer white) + themed card borders.

## P1 — makes the switcher real
- [x] **Stock the 4 empty categories.** Added one poster each: cricket (Virat Kohli), anime (Rengoku), nature (Mt Fuji), motivation (Work Hard). Product page now hides the car "Specs" panel when `specs` is empty.
- [x] **Product page rebuilt.** Customization stripped; hierarchy = details (poster + spec highlights + full Specifications table + 360 view) → detailed description → wall preview → reviews → more products. Add to Cart + Save kept.
- [x] **Structured checkout address** (Amazon-style: country/name/phone/street/unit/city/state/zip + summary).
- [x] **"All Frames" hero marquee.** 3 rows of frames, pure CSS (top/bottom → right, middle → left), blurred + low-opacity, reduced-motion aware. Only renders for `cat=all`.
- [x] **Category landing pages.** Homepage is now category-driven (`/?cat=<key>`): per-category hero title/copy/image, "explore" collection cards, and split-story — all pulled from `CATEGORY_CONTENT` in `main.py`. Picking a category navigates to its page. Empty-state added; car-only theme-explorer removed.
- [ ] **More posters per category.** One each right now. Add depth so grids aren't a single card.
- [ ] **Shop hero copy still car-only.** `shop.html` hero ("Find your wall hero", "Explore every automotive poster") is shared across categories — make it category-aware or neutral.
- [ ] **Landscape posters crop tall.** Nature (Fuji) is landscape but the hero/frame uses a portrait 3/4 ratio, cropping it. Consider per-orientation framing.

## Deferred / must re-add later
- [ ] **Product customization (frame / size / poster-theme + live pricing).** Removed from the product page per request — must NOT ship live yet. The backend still supports it: `/api/price`, `normalize_config`, `compute_config_price`, and `/cart/add` accept frame/size/poster_theme (currently defaulting to black/A3/racing_stripes). To restore, re-add the selectors + `product.js` configurator that call `/api/price`. Wishlist now stores just the product (no config).

## P2 — polish
- [ ] **Dropdown UX.** Native `<details>` doesn't close on outside-click or Esc. Add both; confirm keyboard/focus behavior.
- [ ] **Accent-driven shadows.** `.button--primary` box-shadow is hardcoded orange `rgba(255,90,31,...)`; make it derive from the active accent.
- [ ] **Signature patterns beyond hero.** Currently homepage hero only. Optionally extend to shop/product hero zones (kept controlled, not full-page).
- [ ] **Tune section-tint strength.** Currently 8% wash. Adjust per taste once real category posters are in.

## P3 — infra / debt
- [ ] **Deploy for a shareable link.** Currently localhost only. Pick a host (Render/Fly/PythonAnywhere) so the site has a public URL.
- [ ] **Image optimization.** Poster PNGs are ~2 MB each. Compress / serve WebP for load performance.
- [ ] **Naming collision.** `poster_theme` (racing_stripes/circuit/minimal) vs new `category` — clarify or rename to avoid confusion.
- [ ] **Category as server-side filter.** Filtering is client-side (`.cat-hidden`). Fine now; revisit if catalog grows large or SEO per-category matters (→ real `/category/<key>` routes).

---

# Admin dashboard + owner analytics — planned build

Scoped 2026-07-29. Nothing implemented yet. Storefront design/behaviour must stay intact.

## Decision

Custom Flask admin + **Stripe Checkout** for payments + **first-party analytics built in-house**.

Not a generic analytics SaaS: product-demand, abandonment and lost-demand questions must join to
`products` / `variants` / `components` / BOM cost / stock, and abandoned-cart recovery is an action
(needs cart contents + email), not a report. Sessionization is needed for funnels anyway, so the
marginal cost of putting traffic analytics on the same pipeline is small. Optional later: Plausible
(~$9/mo) purely to cross-check acquisition against ad-blocker loss.

Rejected: Shopify headless (faster to revenue, ~$39/mo, but no production-queue model and no
catalog-joined analytics). Revisit if revenue is the only goal.

## Blocking security fixes (do in P0, before any admin exists)

- [ ] **`secret_key` fallback `"dev_secret_change_me"`** ([main.py:8](main.py#L8)) — deploy without `FLASK_SECRET_KEY` and sessions are forgeable. Fail fast on missing env var instead.
- [ ] **No CSRF on any POST.** Harmless today, fatal with admin. Per-session token + hidden field, checked in an admin `before_request`.
- [ ] **Cookie flags** — set `SESSION_COOKIE_SECURE` / `HTTPONLY` / `SAMESITE`.
- [ ] **`app.run(debug=True)`** ([main.py:525](main.py#L525)) — never prod; Werkzeug debugger is RCE.
- [ ] **No rate limiting** — login brute-force once auth lands.
- [ ] Privacy page + retention policy (checkout already collects name/email/phone/address).

## Architecture

SQLite + WAL, stdlib `sqlite3` (no ORM, no Alembic; numbered `migrations/*.sql` applied on boot).
Ceiling: multi-instance deploy or heavy analytics write load → port to Postgres, so keep SQL portable.

```
db.py                sqlite3 connect + WAL + row_factory + helpers
schema.sql + migrations/
events.py            POST /api/e collector, sessionization, bot filter, UA parse
rollups.py           nightly metrics_daily + abandonment sweep + digest email
admin/               auth · products · inventory · orders · production
                     customers · discounts · analytics · settings · users
templates/admin/     own base.html — storefront templates untouched
static/css/admin.css · static/vendor/chart.umd.js (self-hosted, no CDN)
static/js/track.js   ~60 lines, navigator.sendBeacon
data/store.db
```

- **Keep `load_products()`'s return shape** when swapping `json.load` → DB query. Every existing template and JS file then keeps working unchanged. This is the whole trick for not breaking the storefront.
- SSR Jinja for tables/forms/filters; Chart.js only for charts. No SPA, no build step.
- Auth = Flask session + `werkzeug.security` hashing (zero new deps). Role check server-side on **every** admin request, not just hidden nav.
- Money in **integer cents** everywhere (current `base_price` floats will drift).
- Admin responsive: sidebar → bottom bar under 900px, tables → cards under 720px.

## Model corrections vs. the naive version

- [ ] **Stock is per component, not per finished variant.** 11 products × 4 frames × 4 sizes = 176 SKUs that never sit in a room. What's held: blank frames by size/finish, paper, mounts, glass, packaging. Needs `components` + `variant_components` (BOM). Low-stock alerts then say "walnut A3: 4 on hand, 6 reserved → 3 queued orders will block". BOM unit costs also give true margin.
- [ ] **Production status is per line item, not per order.** One order = 3 posters; two framed, one blocked on stock. Order-level status can't express that, so orders stall silently. `orders.status` is a derived rollup (least-advanced item), never hand-set.
- [ ] **Three independent status fields**, not one: `payment_status`, `production_status` (per item), `fulfillment_status`.
- [ ] **Reserve, don't just decrement.** `available = on_hand - reserved`. Paid order reserves, production consumes, cancel releases. Without this you oversell between payment and framing.
- [ ] **Carts must move to the DB.** Cart is a signed cookie today ([main.py:195](main.py#L195)) — you cannot analyze or recover a cart you never stored. Every abandonment metric depends on this. Cookie becomes a pointer (cart token) only.

## Workflows

Order lifecycle:
```
cart → checkout → Stripe → webhook confirms paid
  → order created, items production_status=queued, components reserved
  → not enough stock? item=blocked, order flagged
  → production board advances items → all packed → ship queue
  → tracking entered → in_transit → delivered
  exceptions anytime: cancel / QC-fail reprint / return / refund
    → Stripe refund + per-line restock decision (damaged ≠ restock)
```

Per-item production state machine (server-enforced; illegal transition → 409, no admin override):
```
queued → printing → printed → mounting → framing → qc → packed
  ├─ blocked (component stock out)
  ├─ reprint (QC fail — consumes stock again, logged; = cost of quality)
  └─ cancelled (release/restock components)
```
Every transition writes `order_item_events` + `audit_log` (who, when, from, to).

Roles: **owner** (all + users/settings/refunds/prices) · **manager** (all ops + refunds + discounts, settings read-only) · **inventory** (components/stock/blocked items; orders read) · **fulfillment** (production + ship queues, tracking, notes; no prices, no refunds, no customer PII beyond ship address).

## Database — ~28 tables

- **Catalog:** `products` (status active/draft/archived, `deleted_at`, cost, SEO) · `product_images` (position, role) · `product_tags` · `variants` (sku unique, barcode, frame, size, orientation, finish, design, product_type, price/sale/cost cents, low_stock_threshold, image_id, position, status) · `collections` · `collection_products`
- **Inventory:** `components` (sku, type frame/paper/mount/glass/packaging, attrs, on_hand, reserved, low_stock_threshold, unit_cost_cents, supplier, lead_time) · `variant_components` (BOM) · `inventory_adjustments` (append-only ledger: `component_id`, delta, reason ∈ receive/sale/damage/return/correction/cancel_restock, note, order_id, user_id) · `stock_reservations`
- **Carts:** `carts` (token, visitor_hash, session_id, email captured at checkout, status active/converted/abandoned/recovered, subtotal_cents, item_count, last_activity_at, checkout_started_at, abandoned_at, recovery_email_sent_at, order_id) · `cart_items` (soft-delete `removed_at` so removals stay analyzable)
- **Orders:** `orders` · `order_items` (**snapshot** name/variant/sku/unit_price/cost at purchase — reports must not shift when a product is later edited) · `order_item_events` · `order_addresses` · `order_events` · `shipments` · `refunds`
- **Customers:** `customers` (email unique, marketing_opt_in, orders_count, total_spent_cents, first/last_order_at) · `customer_tags` · `customer_notes` (internal, never rendered storefront-side)
- **Discounts:** `discounts` (code nullable for automatic, type percent/fixed/free_shipping, scope all/product/collection, min_subtotal_cents, starts_at, ends_at, usage_limit, per_customer_limit, used_count) · `discount_redemptions`
- **Admin:** `users` (role, active, failed_attempts, locked_until, session_version) · `password_resets` (token **hash**) · `audit_log` (before/after JSON, ip_hash) · `settings` (key → JSON)
- **Analytics:** `analytics_events` · `analytics_sessions` · `metrics_daily` (pre-rolled; dashboards never scan raw events) · `search_queries`

Migration: one-shot `products.json` → `products` + `product_images` + `product_tags`, plus one `variants`
row per frame×size (16) seeded from the existing `compute_config_price` adders so prices don't change.
Keep the JSON as read-only fallback for one release. Cart line items become `{variant_id, qty}` with
price re-resolved server-side (kills stale-price and oversell bugs).

## Analytics events

Every commerce event carries `product_id` / `variant_id` / `cart_id` — the thing a bought tool can't do.

`session_start` · `page_view` · `product_view` · `collection_view` · `product_click` (position, list) ·
`search` · **`search_no_results`** · `filter_apply` · `sort_apply` · `variant_select` · `add_to_cart` ·
**`add_to_cart_blocked`** · `remove_from_cart` · `cart_view` · `checkout_start` · `checkout_step` ·
`payment_start` · `purchase` · `wall_preview_used` · `wishlist_add` · `newsletter_signup`

Derived by SQL, not emitted: abandonment, exit page, session duration, pages/session, journey path, new-vs-returning.

Storefront hooks needed (no visual change): search event in [shop.js:17](static/js/shop.js#L17), click
tracking in [macros/cards.html](templates/macros/cards.html), checkout step events in
[checkout.html](templates/checkout.html), beacon script in [base.html](templates/base.html).

### Funnel — abandonment split three ways

```
sessions → product_view → add_to_cart → cart_view → checkout_start
         → contact_complete → payment_start → purchase
```
- **A. cart → checkout** drop = shipping/total surprise
- **B. contact_complete** drop = form friction
- **C. payment_start with no purchase** = trust, or card declined — separate the two using the Stripe `payment_failed` webhook; different problems, different fixes

"Abandoned at checkout" = `checkout_started_at IS NOT NULL AND order_id IS NULL`. Report count, **value in $**, and the item list. Every funnel filterable by date range, device, source, new-vs-returning, **and product/category**.

Output is an action, not a chart: **recoverable carts table** — email, items, value, age, "send recovery email", recovered-revenue attribution. EU: needs a marketing opt-in checkbox at checkout.

### Demand report — "what are customers looking for"

One ranked table from six signals: product views · list clicks + CTR by slot · **view→cart rate per product** (high views + low adds = price/image problem, not traffic) · **cart→purchase per product** · search terms · **zero-result searches** (⭐ demand for posters you don't sell = the print-next list; highest-value report for a made-to-order shop) · wishlist adds + wall-preview uses · **`add_to_cart_blocked` priced in $** ("walnut A3 stock-out cost $840 in 14 days") · **variant mix** (which frame/size sells → feeds the component reorder list).

That last loop — analytics → BOM → purchasing — is the reason to build in-house.

## Owner reports

- **Money:** revenue gross/net · **gross margin from real BOM cost** · AOV · units/order · discount cost as % revenue · refund rate + reasons · shipping charged vs paid · tax · revenue by category · prev-period + same-period-last-year compare
- **Product & stock:** sell-through · **days of cover** per component · dead stock (0 sales 60d) · **reorder list** (reserved+queued vs on_hand, supplier, lead time) · margin ranked · price-change impact
- **Customers:** new vs returning **revenue** split (not visits) · repeat rate · time-to-second-order · **LTV cohorts by first-order month** · top spenders · inactive/at-risk · geo concentration
- **Acquisition:** sessions / conversion / **revenue** by source · landing-page performance · UTM rollup
- **Operations:** throughput/day · **time per station** (where framing jams) · SLA breaches / overdue · **blocked-hours from stock-outs** · **reprint rate = cost of quality** · on-time ship rate · cancel reasons
- **Alerts:** low stock · failed payment · order stuck > N hours · refund spike · **zero-result search trending up** · abandoned cart over $X
- **Digests:** daily email (revenue, orders, top product, abandoned value, blocked orders) + weekly (trends, reorder list, demand report). Owner won't open a dashboard daily — one digest beats five more charts.

## Admin screens

1. **Action Board** (`/admin`) — landing is a work queue, not a chart wall: payment failed · ready to produce · in production · **blocked on stock** · ready to pack · ready to ship · in transit · overdue (aging > SLA) · returns/refunds pending
2. **Production board** — columns = stations, cards = line items (order #, thumb, frame/size, age). Advance **buttons** not drag-only, so it works on a phone in the workshop. Age badge reddens past SLA
3. **Orders** — 3 status fields as separate filters; detail = per-item production timeline, payment/refund panel, tracking, internal notes
4. **Ship queue** — packed orders, batch pack-slip print, tracking entry
5. **Inventory** — components with on_hand / reserved / available, receive form, adjustment ledger, reorder list
6. **Overview** — KPIs, trends, funnel, demand report

## Privacy

Cookieless visitor ID (daily-rotating salted hash of IP+UA, Plausible's method). Raw IP discarded after
country lookup. Cart cookie is strictly-necessary/functional → **no consent banner required**. Marketing
checkbox only for recovery email. Privacy page + customer export/delete path. Deploy behind Cloudflare →
`CF-IPCountry` gives geo free, no MaxMind. Never store raw IP, full UA, email in events, or free text
beyond a truncated search query. Bot-filter known crawler UAs.

**Honest limit:** ad-blockers eat 20–40% of *behavior* events. Orders/revenue/margin/stock come from the
DB and are exact. Dashboard must label which is which — never mix an estimate and a fact in one tile.

## Phases — ≈49–61 dev-days

Sellable at end of P3. Owner-grade product analytics at end of P4. Runtime ≈$15–30/mo, no analytics SaaS fee.

- [ ] **P0 Foundation** (10–12 d) — SQLite + schema + JSON migration + `load_products()` swap + **server-side carts** + Stripe Checkout + webhooks + real orders + the blocking security fixes above
- [ ] **P1 Security** (5–6 d) — auth, 4 roles, CSRF, rate-limit, audit log, responsive admin shell
- [ ] **P2 Catalog & stock** (7–9 d) — products, variants, components/BOM, reservations, adjustment ledger, reorder list, low-stock alerts, archive/restore + confirm-to-delete
- [ ] **P3 Orders & production** (7–9 d) — Action Board, production board, ship queue, cancel/return/refund + restock, invoices, pack slips
- [ ] **P4 Analytics engine** (8–10 d) — `/api/e` collector, sessionization, rollups, **full funnel + abandonment + recoverable carts + demand report + lost demand**, overview KPIs, prev-period compare
- [ ] **P5 Traffic & customers** (6–7 d) — sources, device, geo, exit pages, journeys, new-vs-returning; customer profiles, tags, LTV cohorts, gated export
- [ ] **P6 Growth & ops** (6–8 d) — discount engine, merchandising controls, settings, **email alerts + digests**, ops metrics, CSV import/export + bulk edit

Optional pull-forward: cart/checkout event slice of P4 into P0 (carts already stored there) → funnel +
recoverable-carts ≈2 extra days, before the admin shell exists.

## Test gate — every phase

Unauthenticated + wrong-role hits on every admin route → 403/redirect · stock never negative and
ledger sum == cached on_hand · variant SKU uniqueness · every illegal status transition rejected
server-side · analytics events land with correct sessionization · admin renders at 360/768/1280px ·
every nav item loads real data (no stubs, no placeholder charts) · **existing 13 storefront tests stay green**.

## Risks

| Risk | Mitigation |
|---|---|
| Payments / PCI | Stripe hosted Checkout only. Card data never touches the server (SAQ-A) |
| SQLite single file, no backup | Nightly `VACUUM INTO` + off-box copy from day one. Non-negotiable |
| GDPR / ePrivacy | Cookieless analytics, no PII in events, privacy page, export/delete path |
| Accidental data loss | Archive/trash + `deleted_at`, typed confirmation for hard delete, audit log with before/after |
| Analytics under-count | Label as sampled; revenue/orders always from DB |
| Scope (7 phases solo) | Ship P0–P4, sell, then decide if P5/P6 still matter |
| Bus factor | Custom = maintained forever by you. Real cost vs. Shopify |
