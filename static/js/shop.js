function qs(sel, root=document){ return root.querySelector(sel); }
function qsa(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }

function unique(arr){ return Array.from(new Set(arr)); }

function initBrandOptions(){
  const cards = qsa(".productCard");
  const brands = unique(cards.map(c => c.dataset.brand)).sort();
  const brandSel = qs("#brand");
  brands.forEach(b => {
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = b;
    brandSel.appendChild(opt);
  });
}

function applyFilters(){
  const q = (qs("#q").value || "").trim().toLowerCase();
  const brand = qs("#brand").value;
  const color = qs("#color").value;
  const sort = qs("#sort").value;

  let cards = qsa(".productCard");

  // filter
  cards.forEach(c => {
    const okBrand = !brand || c.dataset.brand === brand;
    const okColor = !color || c.dataset.color === color;

    const hay = `${c.dataset.name} ${c.dataset.tags}`;
    const okQ = !q || hay.includes(q);

    c.style.display = (okBrand && okColor && okQ) ? "" : "none";
  });

  // sort visible only
  const grid = qs("#grid");
  const visible = cards.filter(c => c.style.display !== "none");

  visible.sort((a,b) => {
    const pa = parseFloat(a.dataset.price || "0");
    const pb = parseFloat(b.dataset.price || "0");
    const na = a.dataset.name || "";
    const nb = b.dataset.name || "";
    const fa = a.dataset.featured === "1" ? 1 : 0;
    const fb = b.dataset.featured === "1" ? 1 : 0;

    if(sort === "featured") return fb - fa || na.localeCompare(nb);
    if(sort === "price_asc") return pa - pb;
    if(sort === "price_desc") return pb - pa;
    if(sort === "name_asc") return na.localeCompare(nb);
    return 0;
  });

  // append in order
  visible.forEach(c => grid.appendChild(c));
}

document.addEventListener("DOMContentLoaded", () => {
  initBrandOptions();
  ["#q","#brand","#color","#sort"].forEach(sel => qs(sel).addEventListener("input", applyFilters));
  qs("#clear").addEventListener("click", () => {
    qs("#q").value = "";
    qs("#brand").value = "";
    qs("#color").value = "";
    qs("#sort").value = "featured";
    applyFilters();
  });
  applyFilters();
});
