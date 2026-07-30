function qs(sel, root = document) { return root.querySelector(sel); }

function getWishlist() {
  try { return JSON.parse(localStorage.getItem("wishlist") || "[]"); } catch (e) { return []; }
}
function setWishlist(items) {
  localStorage.setItem("wishlist", JSON.stringify(items));
  const el = qs("#wishlistCount");
  if (el) el.textContent = String(items.length);
}

// Add-to-cart micro feedback (form posts to /cart/add; server uses default config).
function initAddToCart() {
  const form = qs("#addForm");
  const btn = qs("#addToCartBtn");
  if (!form || !btn) return;
  form.addEventListener("submit", () => {
    btn.textContent = "Added ✓";
    setTimeout(() => (btn.textContent = "Add to cart"), 900);
  });
}

// Save to wishlist (no per-design config anymore — just the product).
function initWishlistSave() {
  const btn = qs("#saveWishlistBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const item = { id: window.__PRODUCT__.slug, slug: window.__PRODUCT__.slug, name: window.__PRODUCT__.name, created_at: Date.now() };
    const list = getWishlist();
    if (!list.some(x => x.id === item.id)) list.unshift(item);
    setWishlist(list);
    btn.innerHTML = "Saved ✓";
    setTimeout(() => (btn.innerHTML = '<span aria-hidden="true">♡</span> Save'), 1000);
  });
}

// 360° drag viewer (falls back to the poster when <4 frames exist).
function init360() {
  const viewer = qs("#viewer360");
  const img = qs("#viewerImg");
  if (!viewer || !img) return;
  const frames = JSON.parse(viewer.dataset.frames || "[]");
  const fallback = viewer.dataset.fallback;
  const frameList = (frames && frames.length >= 4) ? frames : [fallback];
  if (frameList.length < 2) return; // nothing to rotate
  let idx = 0, down = false, startX = 0;
  const setFrame = i => { idx = (i + frameList.length) % frameList.length; img.src = frameList[idx]; };
  viewer.addEventListener("pointerdown", e => { down = true; startX = e.clientX; viewer.setPointerCapture(e.pointerId); });
  viewer.addEventListener("pointerup", () => (down = false));
  viewer.addEventListener("pointercancel", () => (down = false));
  viewer.addEventListener("pointermove", e => {
    if (!down) return;
    const dx = e.clientX - startX;
    if (Math.abs(dx) > 14) { setFrame(idx + (dx > 0 ? 1 : -1)); startX = e.clientX; }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initAddToCart();
  initWishlistSave();
  init360();
});
