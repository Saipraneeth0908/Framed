// Category theme switcher: reskins the site (accent via html[data-theme]) and
// filters posters (html[data-cat] + .cat-hidden). Persists the choice.
(function () {
  const KEY = "fo-category";
  const root = document.documentElement;
  const get = s => document.querySelector(s);
  const getAll = s => Array.from(document.querySelectorAll(s));

  function stored() { return localStorage.getItem(KEY) || "all"; }

  function apply(cat) {
    const btn = get(`[data-cat-btn="${cat}"]`);
    const label = btn ? btn.dataset.label : "All frames";
    const tagline = btn ? btn.dataset.tagline : "";

    if (cat === "all") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", cat);
    root.setAttribute("data-cat", cat);

    // Filter product cards (works on any page that renders them).
    getAll(".product-card").forEach(card => {
      card.classList.toggle("cat-hidden", cat !== "all" && card.dataset.category !== cat);
    });

    // Reflect selection in the UI.
    getAll("[data-cat-btn]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.catBtn === cat)));
    getAll("[data-cat-current]").forEach(el => (el.textContent = label));
    getAll("[data-cat-tagline]").forEach(el => { if (tagline) el.textContent = tagline; });

    localStorage.setItem(KEY, cat);
    // Let page scripts (e.g. shop.js result count) react.
    document.dispatchEvent(new CustomEvent("fo:category", { detail: { category: cat } }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Picking a category navigates to that category's landing page (/?cat=key).
    getAll("[data-cat-btn]").forEach(btn => btn.addEventListener("click", () => {
      const cat = btn.dataset.catBtn;
      localStorage.setItem(KEY, cat);
      window.location.href = cat === "all" ? "/?cat=all" : "/?cat=" + encodeURIComponent(cat);
    }));
    // On load: reflect the active category in the UI + filter grids (shop).
    apply(stored());
  });
})();
