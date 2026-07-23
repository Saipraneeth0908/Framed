function initTabs() {
  document.querySelectorAll("[data-tabs]").forEach(tabs => {
    const tabList = tabs.querySelector('[role="tablist"]');
    const buttons = Array.from(tabs.querySelectorAll('[role="tab"]'));
    const panels = Array.from(tabs.querySelectorAll('[role="tabpanel"]'));
    function activate(button) {
      buttons.forEach(item => { const selected = item === button; item.setAttribute("aria-selected", String(selected)); item.tabIndex = selected ? 0 : -1; });
      panels.forEach(panel => { panel.hidden = panel.id !== button.getAttribute("aria-controls"); });
    }
    buttons.forEach(button => button.addEventListener("click", () => activate(button)));
    tabList.addEventListener("keydown", event => {
      const current = buttons.indexOf(document.activeElement);
      if (current < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus(); activate(buttons[next]);
    });
  });
}

document.addEventListener("DOMContentLoaded", initTabs);
