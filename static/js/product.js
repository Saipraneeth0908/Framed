function qs(sel, root=document){ return root.querySelector(sel); }
function getWishlist(){
  try { return JSON.parse(localStorage.getItem("wishlist") || "[]"); } catch(e){ return []; }
}
function setWishlist(items){
  localStorage.setItem("wishlist", JSON.stringify(items));
  const el = qs("#wishlistCount");
  if(el) el.textContent = String(items.length);
}
function bumpCartCount(){
  const n = parseInt(localStorage.getItem("cartCount") || "0", 10) || 0;
  localStorage.setItem("cartCount", String(n + 1));
  const el = qs("#cartCount");
  if(el) el.textContent = String(n + 1);
}

async function updatePrice(){
  const frame = qs("#frame").value;
  const size = qs("#size").value;
  const poster_theme = qs("#poster_theme").value;

  const res = await fetch("/api/price", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      base_price: window.__PRODUCT__.base_price,
      frame, size, poster_theme
    })
  });
  const data = await res.json();
  qs("#priceNow").textContent = data.price.toFixed(2);

  // Light preview “feel” based on poster_theme (simple overlay changes)
  const frameEl = qs("#posterFrame");
  frameEl.style.boxShadow = (poster_theme === "circuit")
    ? "0 18px 45px rgba(0,0,0,.55), 0 0 0 1px rgba(255,211,90,.18) inset"
    : "0 18px 45px rgba(0,0,0,.55)";

  // Visual cue for frame selection (border tint)
  const tint = {
    black: "rgba(255,255,255,.10)",
    walnut: "rgba(255,138,31,.18)",
    white: "rgba(233,238,246,.18)",
    gold: "rgba(255,211,90,.25)"
  }[frame] || "rgba(255,255,255,.10)";
  frameEl.style.borderColor = tint;

  // Update shareable URL without reloading
  const url = new URL(window.location.href);
  url.searchParams.set("frame", frame);
  url.searchParams.set("size", size);
  url.searchParams.set("poster_theme", poster_theme);
  window.history.replaceState({}, "", url.toString());
}

function initConfigurator(){
  ["#frame","#size","#poster_theme"].forEach(sel => qs(sel).addEventListener("change", updatePrice));
  updatePrice();
}

function initAddToCartAnim(){
  const form = qs("#addForm");
  const btn = qs("#addToCartBtn");
  form.addEventListener("submit", () => {
    // micro animation + update local count
    btn.textContent = "Added ✓";
    btn.style.transform = "translateY(-1px) scale(1.01)";
    bumpCartCount();
    setTimeout(() => {
      btn.textContent = "Add to cart";
      btn.style.transform = "";
    }, 900);
  });
}

function initWishlistSave(){
  const saveBtn = qs("#saveWishlistBtn");
  saveBtn.addEventListener("click", () => {
    const frame = qs("#frame").value;
    const size = qs("#size").value;
    const poster_theme = qs("#poster_theme").value;

    const item = {
      id: `${window.__PRODUCT__.slug}|${frame}|${size}|${poster_theme}`,
      slug: window.__PRODUCT__.slug,
      frame, size, poster_theme,
      created_at: Date.now()
    };

    const list = getWishlist();
    if(!list.some(x => x.id === item.id)) list.unshift(item);
    setWishlist(list);

    saveBtn.textContent = "Saved ✓";
    setTimeout(() => saveBtn.textContent = "Save design", 900);
  });
}

function initCopyLink(){
  const btn = qs("#copyLinkBtn");
  btn.addEventListener("click", async () => {
    try{
      await navigator.clipboard.writeText(window.location.href);
      btn.textContent = "Copied ✓";
      setTimeout(()=> btn.textContent="Copy link", 900);
    }catch(e){
      alert("Copy failed. You can manually copy the URL from the address bar.");
    }
  });
}

// C: 360 drag viewer
function init360(){
  const viewer = qs("#viewer360");
  const frames = JSON.parse(viewer.dataset.frames || "[]");
  const fallback = viewer.dataset.fallback;
  const img = qs("#viewerImg");

  const frameList = (frames && frames.length >= 4) ? frames : [fallback, fallback, fallback, fallback];
  let idx = 0;
  let down = false;
  let startX = 0;

  function setFrame(i){
    idx = (i + frameList.length) % frameList.length;
    img.src = frameList[idx];
  }

  viewer.addEventListener("pointerdown", (e) => {
    down = true;
    startX = e.clientX;
    viewer.setPointerCapture(e.pointerId);
  });
  viewer.addEventListener("pointerup", () => down = false);
  viewer.addEventListener("pointercancel", () => down = false);
  viewer.addEventListener("pointermove", (e) => {
    if(!down) return;
    const dx = e.clientX - startX;
    if(Math.abs(dx) > 14){
      setFrame(idx + (dx > 0 ? 1 : -1));
      startX = e.clientX;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initConfigurator();
  initAddToCartAnim();
  initWishlistSave();
  initCopyLink();
  init360();
});
