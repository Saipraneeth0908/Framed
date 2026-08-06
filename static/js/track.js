/* First-party analytics beacon.
 *
 * No cookie is set: the session id lives in sessionStorage and the visitor is
 * identified server-side by a rotating salted hash of an IP that is never
 * stored. That is why this needs no consent banner.
 *
 * sendBeacon, not fetch: it survives page unload, which is the only way to get
 * honest exit-page and duration data. */
(function () {
  "use strict";

  var ENDPOINT = document.currentScript && document.currentScript.dataset.endpoint;
  if (!ENDPOINT) return;
  if (navigator.doNotTrack === "1" || window.doNotTrack === "1") return;

  var SESSION_KEY = "fo-analytics-sid";
  var queue = [];
  var timer = null;

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function sessionId() {
    var id;
    try {
      id = sessionStorage.getItem(SESSION_KEY);
      if (!id) { id = uuid(); sessionStorage.setItem(SESSION_KEY, id); }
    } catch (e) { id = uuid(); }   /* private mode: one session per page */
    return id;
  }

  var utm = (function () {
    var params = new URLSearchParams(location.search), out = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"].forEach(function (k) {
      var v = params.get(k);
      if (v) out[k.slice(4)] = v.slice(0, 100);
    });
    return out;
  })();

  var referrerHost = "";
  try {
    if (document.referrer && new URL(document.referrer).host !== location.host) {
      referrerHost = new URL(document.referrer).host;
    }
  } catch (e) { /* malformed referrer */ }

  function flush() {
    if (!queue.length) return;
    var batch = queue.splice(0, 50);
    var body = JSON.stringify(batch);
    /* sendBeacon can refuse (queue full, body too large). fetch with keepalive
       is the fallback, and a dropped analytics event is never worth an error. */
    var sent = false;
    try { sent = navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" })); }
    catch (e) { sent = false; }
    if (!sent && window.fetch) {
      fetch(ENDPOINT, { method: "POST", body: body, keepalive: true, mode: "cors",
                        headers: { "Content-Type": "application/json" } }).catch(function () {});
    }
  }

  function track(name, props) {
    queue.push({
      event_id: uuid(),
      session_id: sessionId(),
      occurred_at: Date.now(),
      name: name,
      path: location.pathname,
      referrer_host: referrerHost,
      utm: utm,
      props: props || {}
    });
    /* Batch on a 1s debounce so a burst of filter clicks is one request. */
    clearTimeout(timer);
    timer = setTimeout(flush, 1000);
    if (queue.length >= 20) flush();
  }

  window.foTrack = track;

  track("page_view", { title: document.title.slice(0, 200) });

  /* Product detail: the slug is on the add-to-cart form. */
  var addForm = document.getElementById("addForm");
  if (addForm) {
    var slugInput = addForm.querySelector('[name="slug"]');
    var slug = slugInput ? slugInput.value : "";
    track("product_view", { slug: slug });
    addForm.addEventListener("submit", function () {
      track("add_to_cart", {
        slug: slug,
        frame: (addForm.querySelector('[name="frame"]') || {}).value,
        size: (addForm.querySelector('[name="size"]') || {}).value,
        poster_theme: (addForm.querySelector('[name="poster_theme"]') || {}).value,
        qty: (addForm.querySelector('[name="qty"]') || {}).value
      });
      flush();
    });
    addForm.addEventListener("change", function (event) {
      if (event.target.name) track("config_change", { field: event.target.name, value: event.target.value });
    });
  }

  /* Catalogue search. Zero-result searches are the whole point of this event:
     they are demand we are failing to meet. */
  var search = document.getElementById("searchInput") || document.querySelector('[data-search-input]');
  if (search) {
    var debounce = null;
    search.addEventListener("input", function () {
      clearTimeout(debounce);
      debounce = setTimeout(function () {
        var term = search.value.trim();
        if (term.length < 2) return;
        var visible = document.querySelectorAll(".product-card:not([hidden])").length;
        track(visible === 0 ? "search_zero_results" : "search", { term: term.slice(0, 100), results: visible });
      }, 700);
    });
  }

  document.addEventListener("click", function (event) {
    var card = event.target.closest && event.target.closest(".product-card");
    if (card) {
      var link = card.querySelector("a[href]");
      track("outbound_click", { to: link ? link.getAttribute("href") : "", from: location.pathname });
    }
    var filter = event.target.closest && event.target.closest("[data-filter]");
    if (filter) track("filter_apply", { filter: filter.dataset.filter, value: filter.value || filter.textContent.trim() });
  }, { passive: true });

  if (document.body.dataset.page === "cart") track("cart_view", {});
  if (document.body.dataset.page === "checkout") {
    track("checkout_start", {});
    var checkoutForm = document.querySelector(".address-form");
    if (checkoutForm) {
      checkoutForm.addEventListener("submit", function () { track("checkout_step", { step: "submit" }); flush(); });
    }
    if (document.querySelector(".checkout-success, [data-checkout-success]")) track("purchase", {});
    var error = document.querySelector(".form-message--error, .checkout-error");
    if (error) track("checkout_error", { message: error.textContent.trim().slice(0, 200) });
  }

  /* Last chance to ship whatever is queued. visibilitychange fires on mobile
     where unload often does not. */
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flush();
  });
  window.addEventListener("pagehide", flush);
})();
