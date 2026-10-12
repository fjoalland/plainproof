// Installed in every page: records the text of transient notifications (toasts, snackbars,
// alerts, live regions) as they appear. A "saved successfully" toast lives a few seconds:
// by the time the agent decides to check it, it may be gone, and a working application
// would fail its test.
(() => {
  if (window.__ppTransientInstalled) return;
  window.__ppTransientInstalled = true;
  window.__ppTransient = [];
  const SELECTOR = '[role=alert],[role=status],[aria-live],.p-toast,.p-message,.toast,.Toastify,.snackbar,'
    + '.v-snackbar,.mat-mdc-snack-bar-container,.mat-snack-bar-container,.el-message,.el-notification,'
    + '.ant-message,.ant-notification,.notification,.notyf,.swal2-popup';
  const grab = el => setTimeout(() => {
    const text = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    const list = window.__ppTransient;
    if (!text || (list.length && list[list.length - 1].text === text)) return;
    list.push({ t: Date.now(), text: text.slice(0, 500) });
    if (list.length > 50) list.shift();
  }, 60);
  const start = () => new MutationObserver(mutations => {
    for (const m of mutations) {
      const el = m.target.nodeType === 1 ? m.target : m.target.parentElement;
      const box = el && el.closest && el.closest(SELECTOR);
      if (box) { grab(box); continue; }
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        const inner = node.matches(SELECTOR) ? node : node.querySelector(SELECTOR);
        if (inner) grab(inner);
      }
    }
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  if (document.documentElement) start(); else document.addEventListener('DOMContentLoaded', start);
})();
