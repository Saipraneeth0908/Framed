function qs(selector, root = document) { return root.querySelector(selector); }
function qsa(selector, root = document) { return Array.from(root.querySelectorAll(selector)); }

function getWishlist() {
  try { return JSON.parse(localStorage.getItem("wishlist") || "[]"); }
  catch (_) { return []; }
}

function setWishlist(items) {
  localStorage.setItem("wishlist", JSON.stringify(items));
  const badge = qs("#wishlistCount");
  if (badge) badge.textContent = String(items.length);
  renderWishlist();
}

function renderWishlist() {
  const body = qs("#wishlistBody");
  if (!body) return;
  const items = getWishlist();
  const badge = qs("#wishlistCount");
  if (badge) badge.textContent = String(items.length);
  if (!items.length) {
    body.innerHTML = `<div class="empty-state"><h3>No saved designs yet</h3><p class="muted">Configure a poster, then save that exact combination here.</p><a class="button button--primary" href="/shop">Explore posters</a></div>`;
    return;
  }
  body.innerHTML = items.map(item => `
    <div class="wishlist-item">
      <a href="/product/${encodeURIComponent(item.slug)}?frame=${encodeURIComponent(item.frame)}&size=${encodeURIComponent(item.size)}&poster_theme=${encodeURIComponent(item.poster_theme)}">
        <strong>${item.slug.replaceAll("-", " ")}</strong>
        <small>${item.frame} · ${item.size} · ${item.poster_theme.replaceAll("_", " ")}</small>
      </a>
      <button class="wishlist-remove" type="button" data-remove-wishlist="${item.id}" aria-label="Remove saved design">Remove</button>
    </div>`).join("");
  qsa("[data-remove-wishlist]", body).forEach(button => button.addEventListener("click", () => {
    setWishlist(getWishlist().filter(item => item.id !== button.dataset.removeWishlist));
  }));
}

function initDrawers() {
  const backdrop = qs("#drawerBackdrop");
  const triggers = [
    [qs("#menuToggle"), qs("#mobileNav")],
    [qs("#wishlistBtn"), qs("#wishlistDrawer")],
    [qs("#cartDrawerBtn"), qs("#cartDrawer")]
  ];
  let activeDrawer = null;
  let previousFocus = null;

  function close() {
    if (!activeDrawer) return;
    activeDrawer.classList.remove("open");
    activeDrawer.setAttribute("aria-hidden", "true");
    triggers.forEach(([trigger]) => trigger?.setAttribute("aria-expanded", "false"));
    backdrop.classList.remove("show");
    backdrop.hidden = true;
    document.body.classList.remove("drawer-open");
    activeDrawer = null;
    previousFocus?.focus();
  }

  function open(trigger, drawer) {
    close();
    previousFocus = trigger;
    activeDrawer = drawer;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    trigger.setAttribute("aria-expanded", "true");
    backdrop.hidden = false;
    requestAnimationFrame(() => backdrop.classList.add("show"));
    document.body.classList.add("drawer-open");
    qs("button, a, input", drawer)?.focus();
  }

  triggers.forEach(([trigger, drawer]) => trigger && drawer && trigger.addEventListener("click", () => open(trigger, drawer)));
  qsa(".drawer-close").forEach(button => button.addEventListener("click", close));
  backdrop?.addEventListener("click", close);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") close();
    if (event.key !== "Tab" || !activeDrawer) return;
    const focusable = qsa('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])', activeDrawer);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
}

function initReveal() {
  const elements = qsa(".reveal");
  if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    elements.forEach(element => element.classList.add("is-visible")); return;
  }
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add("is-visible"); observer.unobserve(entry.target); }
  }), { threshold: .12 });
  elements.forEach(element => observer.observe(element));
}

document.addEventListener("DOMContentLoaded", () => {
  renderWishlist();
  initDrawers();
  initReveal();
});
