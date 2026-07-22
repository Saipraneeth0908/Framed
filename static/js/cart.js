// static/js/cart.js

function qs(sel, root = document) { return root.querySelector(sel); }
function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

function setLocalCartCountFromPage() {
  // Count total quantity shown on cart page
  const qtyInputs = qsa("input.qty");
  let total = 0;
  qtyInputs.forEach(inp => {
    const v = parseInt(inp.value || "0", 10);
    total += isNaN(v) ? 0 : v;
  });

  localStorage.setItem("cartCount", String(total));
  const badge = qs("#cartCount");
  if (badge) badge.textContent = String(total);
}

function initAutoUpdateQty() {
  // Optional: auto-submit update form when qty changes (nice UX)
  const qtyInputs = qsa("input.qty");
  qtyInputs.forEach(inp => {
    inp.addEventListener("change", () => {
      const form = inp.closest("form");
      if (!form) return;
      form.submit();
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setLocalCartCountFromPage();
  initAutoUpdateQty();
});
