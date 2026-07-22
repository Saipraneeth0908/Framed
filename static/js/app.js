function qs(sel, root=document){ return root.querySelector(sel); }
function qsa(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }

function getLocalCartCount(){
  // cart count is server-side; keep a lightweight UI count in localStorage as a helper
  const n = parseInt(localStorage.getItem("cartCount") || "0", 10);
  return isNaN(n) ? 0 : n;
}
function setLocalCartCount(n){
  localStorage.setItem("cartCount", String(n));
  const el = qs("#cartCount");
  if(el) el.textContent = String(n);
}

function getWishlist(){
  try { return JSON.parse(localStorage.getItem("wishlist") || "[]"); }
  catch(e){ return []; }
}
function setWishlist(items){
  localStorage.setItem("wishlist", JSON.stringify(items));
  const el = qs("#wishlistCount");
  if(el) el.textContent = String(items.length);
}

function initCounts(){
  setLocalCartCount(getLocalCartCount());
  setWishlist(getWishlist());
}

function initDrawer(){
  const drawer = qs("#cartDrawer");
  const backdrop = qs("#drawerBackdrop");
  const openBtn = qs("#cartDrawerBtn");
  const closeBtn = qs("#closeDrawerBtn");

  function open(){
    drawer.classList.add("open");
    backdrop.classList.add("show");
    drawer.setAttribute("aria-hidden", "false");
  }
  function close(){
    drawer.classList.remove("open");
    backdrop.classList.remove("show");
    drawer.setAttribute("aria-hidden", "true");
  }

  if(openBtn) openBtn.addEventListener("click", open);
  if(closeBtn) closeBtn.addEventListener("click", close);
  if(backdrop) backdrop.addEventListener("click", close);
}

function initCardTilt(){
  qsa(".card").forEach(card => {
    card.addEventListener("mousemove", (e) => {
      const r = card.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      card.style.transform = `translateY(-4px) rotateX(${(-y*5).toFixed(2)}deg) rotateY(${(x*7).toFixed(2)}deg)`;
    });
    card.addEventListener("mouseleave", () => {
      card.style.transform = "";
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initCounts();
  initDrawer();
  initCardTilt();
});
