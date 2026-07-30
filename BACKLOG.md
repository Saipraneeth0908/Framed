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
