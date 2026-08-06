/* First-party behavioural analytics.
 *
 * No cookie of its own: the session id is minted server-side and lives in the
 * strictly-necessary cart cookie, so the beacon and the cart share one key and
 * behaviour can be joined to money. That join is the entire point -- "people
 * looked at this a lot" is worthless next to "people looked at this a lot and
 * never bought it".
 *
 * sendBeacon rather than fetch: it survives page unload, which is the only way
 * to get honest dwell-time and exit-page data.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;
  var ENDPOINT = script.dataset.endpoint;
  if (!ENDPOINT) return;
  if (navigator.doNotTrack === "1" || window.doNotTrack === "1") return;

  var SID = script.dataset.sid || "";
  var PAGE = script.dataset.page || "";
  var queue = [];
  var timer = null;

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  if (!SID) {
    /* Server did not supply one (a cached page, say). Fall back to a local id
       so the events are still self-consistent, even though they will not join
       to a cart. */
    try {
      SID = sessionStorage.getItem("fo-sid") || uuid();
      sessionStorage.setItem("fo-sid", SID);
    } catch (e) { SID = uuid(); }
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
      session_id: SID,
      occurred_at: Date.now(),
      name: name,
      path: location.pathname,
      referrer_host: referrerHost,
      utm: utm,
      props: props || {}
    });
    clearTimeout(timer);
    timer = setTimeout(flush, 1000);
    if (queue.length >= 20) flush();
  }

  window.foTrack = track;

  /* ------------------------------------------------------------------ *
   * Dwell time. Wall-clock on a page is a lie -- a tab left open over
   * lunch is not ninety minutes of attention. Only time with the tab
   * actually visible is accumulated.
   * ------------------------------------------------------------------ */
  var activeMs = 0;
  var lastResume = document.visibilityState === "visible" ? Date.now() : 0;
  var maxScrollPct = 0;
  var clickCount = 0;
  var exited = false;

  function activeSeconds() {
    var total = activeMs + (lastResume ? Date.now() - lastResume : 0);
    return Math.round(total / 1000);
  }

  function scrollPct() {
    var doc = document.documentElement;
    var scrollable = doc.scrollHeight - window.innerHeight;
    if (scrollable <= 0) return 100;      /* short page: fully seen */
    return Math.min(100, Math.round(((window.scrollY || 0) / scrollable) * 100));
  }

  var scrollTimer = null;
  window.addEventListener("scroll", function () {
    if (scrollTimer) return;
    scrollTimer = setTimeout(function () {
      scrollTimer = null;
      var pct = scrollPct();
      if (pct > maxScrollPct) maxScrollPct = pct;
    }, 250);
  }, { passive: true });

  function sendExit(reason) {
    if (exited) return;
    exited = true;
    track("page_exit", {
      page: PAGE,
      active_seconds: activeSeconds(),
      scroll_pct: Math.max(maxScrollPct, scrollPct()),
      clicks: clickCount,
      reason: reason
    });
    flush();
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      if (lastResume) { activeMs += Date.now() - lastResume; lastResume = 0; }
      sendExit("hidden");
    } else {
      lastResume = Date.now();
      exited = false;                     /* returning tab starts a new leg */
    }
  });
  window.addEventListener("pagehide", function () { sendExit("unload"); });

  /* Heartbeat so a long read is not lost if the exit beacon never fires. */
  setInterval(function () {
    if (document.visibilityState === "visible" && activeSeconds() > 0) {
      track("page_heartbeat", { page: PAGE, active_seconds: activeSeconds(), scroll_pct: maxScrollPct });
    }
  }, 30000);

  /* ------------------------------------------------------------------ *
   * Page and product context
   * ------------------------------------------------------------------ */
  track("page_view", { page: PAGE, title: document.title.slice(0, 200) });

  var addForm = document.getElementById("addForm");
  var currentSlug = "";
  if (addForm) {
    var slugInput = addForm.querySelector('[name="slug"]');
    currentSlug = slugInput ? slugInput.value : "";
    track("product_view", { slug: currentSlug });

    addForm.addEventListener("submit", function () {
      track("add_to_cart", {
        slug: currentSlug,
        frame: value(addForm, "frame"),
        size: value(addForm, "size"),
        poster_theme: value(addForm, "poster_theme"),
        qty: value(addForm, "qty"),
        seconds_to_add: activeSeconds()
      });
      flush();
    });
    addForm.addEventListener("change", function (event) {
      if (event.target.name) {
        track("config_change", { slug: currentSlug, field: event.target.name, value: event.target.value });
      }
    });
  }

  function value(form, name) {
    var el = form.querySelector('[name="' + name + '"]');
    return el ? el.value : "";
  }

  /* ------------------------------------------------------------------ *
   * Clicks. Recorded by role, not by pixel: a heatmap of coordinates is
   * a screenshot, whereas "which control" is something you can act on.
   * ------------------------------------------------------------------ */
  document.addEventListener("click", function (event) {
    clickCount++;
    var el = event.target.closest ? event.target.closest("a, button, [data-cat-btn], [data-filter], .product-card") : null;
    if (!el) return;

    var card = el.classList && el.classList.contains("product-card") ? el : null;
    if (card) {
      var link = card.querySelector("a[href]");
      var href = link ? link.getAttribute("href") : "";
      track("product_click", {
        slug: href.indexOf("/product/") === 0 ? href.slice(9) : "",
        from: location.pathname,
        position: [].indexOf.call(document.querySelectorAll(".product-card"), card) + 1
      });
      return;
    }
    if (el.dataset && el.dataset.catBtn) {
      track("category_switch", { category: el.dataset.catBtn });
      return;
    }
    if (el.dataset && el.dataset.filter) {
      track("filter_apply", { filter: el.dataset.filter, value: (el.value || el.textContent || "").trim().slice(0, 60) });
      return;
    }
    track("click", {
      target: (el.id || el.className || el.tagName).toString().slice(0, 80),
      text: (el.textContent || "").trim().slice(0, 60),
      href: el.getAttribute ? (el.getAttribute("href") || "") : ""
    });
  }, { passive: true, capture: true });

  /* ------------------------------------------------------------------ *
   * Wishlist. Saving something and never buying it is the single clearest
   * statement of intent a visitor makes, so it gets its own events.
   * ------------------------------------------------------------------ */
  document.addEventListener("click", function (event) {
    var save = event.target.closest && event.target.closest("[data-save-design], #saveDesign, .wishlist-add");
    if (save) track("wishlist_add", { slug: currentSlug || save.dataset.slug || "" });
    var remove = event.target.closest && event.target.closest("[data-remove-wishlist]");
    if (remove) track("wishlist_remove", { design_id: remove.dataset.removeWishlist || "" });
  }, { passive: true, capture: true });

  /* Search. Zero-result searches are demand we are failing to meet. */
  var search = document.getElementById("searchInput") || document.querySelector("[data-search-input]");
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

  /* Cart and checkout */
  if (PAGE === "cart") {
    track("cart_view", { lines: document.querySelectorAll(".cartItem").length });
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (form.getAttribute("action") === "/cart/update") {
        var qty = form.querySelector('[name="qty"]');
        track(qty && qty.value === "0" ? "remove_from_cart" : "cart_update", { qty: qty ? qty.value : "" });
      }
      if (form.getAttribute("action") === "/cart/clear") track("cart_clear", {});
    }, true);
  }

  if (PAGE === "checkout") {
    var success = document.querySelector(".checkout-success, [data-checkout-success]");
    if (success) {
      track("purchase", { seconds_to_purchase: activeSeconds() });
    } else {
      track("checkout_start", {});
      var checkoutForm = document.querySelector(".address-form");
      if (checkoutForm) {
        checkoutForm.addEventListener("submit", function () {
          track("checkout_step", { step: "submit", seconds_on_form: activeSeconds() });
          flush();
        });
        /* Which field they abandon on is the actionable part of a drop-off. */
        checkoutForm.addEventListener("focusout", function (event) {
          if (event.target.name && !event.target.value) {
            track("checkout_field_blank", { field: event.target.name });
          }
        }, true);
      }
    }
    var error = document.querySelector(".form-message--error, .checkout-error, .alert--error");
    if (error) track("checkout_error", { message: error.textContent.trim().slice(0, 200) });
  }

  if (PAGE === "newsletter" || document.querySelector(".updates-form")) {
    var updates = document.querySelector(".updates-form");
    if (updates) updates.addEventListener("submit", function () { track("newsletter_submit", {}); });
  }
})();
