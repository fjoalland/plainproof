// A text that is in the page but not rendered (collapsed menu, closed accordion, inactive tab),
// and the toggle that most plausibly reveals it: {toggle, ref} or null.
(args) => {
  const norm = s => (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let holder = null;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) continue;
    if (!norm(el.textContent).includes(args.needle)) continue;
    if (el.checkVisibility && el.checkVisibility({ checkVisibilityCSS: true })) continue;
    holder = el;
    break;
  }
  if (!holder) return null;
  const label = t => (t.getAttribute('aria-label') || t.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 60);
  const visible = t => !t.checkVisibility || t.checkVisibility({ checkVisibilityCSS: true });
  // 1. a toggle that declares what it controls, or the <summary> of a closed <details>
  for (let a = holder; a && a !== document.body; a = a.parentElement) {
    if (a.id) {
      const toggle = document.querySelector('[aria-controls~="' + CSS.escape(a.id) + '"]');
      if (toggle && visible(toggle)) return { toggle: label(toggle), ref: toggle.getAttribute(args.refAttr) };
    }
    if (a.tagName === 'DETAILS') {
      const summary = a.querySelector('summary');
      if (summary) return { toggle: label(summary), ref: summary.getAttribute(args.refAttr) };
    }
  }
  // 2. the nearest collapsed toggle before the hidden block, in document order
  let best = null;
  for (const toggle of document.querySelectorAll('[aria-expanded=false]')) {
    if (visible(toggle) && (toggle.compareDocumentPosition(holder) & Node.DOCUMENT_POSITION_FOLLOWING)) best = toggle;
  }
  return best ? { toggle: label(best), ref: best.getAttribute(args.refAttr) } : { toggle: '' };
}
