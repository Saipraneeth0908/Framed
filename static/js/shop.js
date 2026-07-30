(function () {
  const get = selector => document.querySelector(selector);
  const getAll = selector => Array.from(document.querySelectorAll(selector));
  const controls = ["q", "brand", "color", "sort"];

  function initBrandOptions() {
    const brands = [...new Set(getAll(".product-card").map(card => card.dataset.brand))].sort();
    brands.forEach(brand => get("#brand").add(new Option(brand, brand)));
  }

  function updateUrl() {
    const params = new URLSearchParams();
    controls.forEach(id => { const value = get(`#${id}`).value; if (value && !(id === "sort" && value === "featured")) params.set(id, value); });
    history.replaceState({}, "", `${location.pathname}${params.size ? `?${params}` : ""}${location.hash}`);
  }

  function applyFilters() {
    const query = get("#q").value.trim().toLowerCase();
    const brand = get("#brand").value, color = get("#color").value, sort = get("#sort").value;
    const cards = getAll(".product-card");
    cards.forEach(card => {
      const haystack = `${card.dataset.name} ${card.dataset.tags} ${card.dataset.series} ${card.dataset.brand}`.toLowerCase();
      card.hidden = !((!query || haystack.includes(query)) && (!brand || card.dataset.brand === brand) && (!color || card.dataset.color === color));
    });
    // Category (theme switcher) hides via .cat-hidden — exclude those from counts too.
    const visible = cards.filter(card => !card.hidden && !card.classList.contains("cat-hidden"));
    visible.sort((a, b) => {
      const pa = Number(a.dataset.price), pb = Number(b.dataset.price);
      if (sort === "price_asc") return pa - pb;
      if (sort === "price_desc") return pb - pa;
      if (sort === "name_asc") return a.dataset.name.localeCompare(b.dataset.name);
      return Number(b.dataset.featured) - Number(a.dataset.featured) || a.dataset.name.localeCompare(b.dataset.name);
    }).forEach(card => get("#grid").append(card));
    get("#resultCount").textContent = `Showing ${visible.length} of ${cards.length} products`;
    get("#catalogEmpty").hidden = visible.length !== 0;
    const filterNames = [["q", query && `Search: ${query}`], ["brand", brand], ["color", color]];
    get("#activeFilters").innerHTML = filterNames.filter(([,value]) => value).map(([id,value]) => `<button type="button" data-clear="${id}">${value}<span aria-hidden="true">×</span><span class="sr-only">Remove filter</span></button>`).join("");
    getAll("[data-clear]").forEach(button => button.addEventListener("click", () => { get(`#${button.dataset.clear}`).value = ""; applyFilters(); }));
    updateUrl();
  }

  function clearFilters() { get("#q").value = ""; get("#brand").value = ""; get("#color").value = ""; get("#sort").value = "featured"; applyFilters(); }
  document.addEventListener("DOMContentLoaded", () => {
    initBrandOptions();
    const params = new URLSearchParams(location.search);
    controls.forEach(id => { if (params.has(id)) get(`#${id}`).value = params.get(id); });
    if (params.get("focus") === "featured") get("#sort").value = "featured";
    controls.forEach(id => get(`#${id}`).addEventListener(id === "q" ? "input" : "change", applyFilters));
    get("#clear").addEventListener("click", clearFilters); get("[data-clear-filters]").addEventListener("click", clearFilters); applyFilters();
    document.addEventListener("fo:category", applyFilters);
  });
})();
