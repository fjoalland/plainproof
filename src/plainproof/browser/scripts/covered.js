// An interactive element whose name matches `wanted`, on screen, but under another element:
// says what covers it ("a calendar", "a dropdown list", "another element", or "fixed bar").
(wanted) => {
  const norm = s => (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  const vw = window.innerWidth, vh = window.innerHeight;
  for (const el of document.querySelectorAll('a[href],button,input,select,textarea,[role=button],[role=link],[role=menuitem],[role=tab]')) {
    const name = norm(el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('title'));
    if (!name || !(name.includes(wanted) || wanted.includes(name))) continue;
    if (el.checkVisibility && !el.checkVisibility({ checkVisibilityCSS: true })) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) continue;
    const top = document.elementFromPoint(Math.min(r.left + r.width / 2, vw - 1), Math.min(r.top + r.height / 2, vh - 1));
    if (!top || el.contains(top) || top.contains(el)) continue;
    // A header or footer fixed to the screen is not a popup: scrolling moves the element from under it.
    if (!top.closest('[role=dialog],[aria-modal=true],dialog')) {
      for (let node = top; node && node !== document.body; node = node.parentElement) {
        if (/^(fixed|sticky)$/.test(getComputedStyle(node).position)) return 'fixed bar';
      }
    }
    const layer = top.closest('[role=dialog],[role=listbox],[role=menu],[class*=datepicker],[class*=calendar],[class*=overlay],[class*=popover],[class*=dropdown],[class*=select]') || top;
    const hint = (layer.className || '') + ' ' + (layer.getAttribute('role') || '');
    if (/date|calendar/i.test(hint)) return 'a calendar';
    if (/listbox|menu|dropdown|select/i.test(hint)) return 'a dropdown list';
    return 'another element';
  }
  return '';
}
