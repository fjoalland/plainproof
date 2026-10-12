// Numbers every interactive element of the page (attribute args.refAttr = "N") and returns
// what the model needs to know about each one: its label, its state and its box.
//
// The WHOLE page is listed, not only the viewport: an element three screens below can be
// clicked directly (the driver scrolls to it). Hunting for elements by scrolling is what
// used to send agents into endless up/down loops.
//
// A modal dialog is the exception: it makes the rest of the page inert, so only what is on
// screen stays listed. A dropdown list or a date picker is not a modal.
(args) => {
  const refAttr = args.refAttr, maxElements = args.max;
  document.querySelectorAll('[' + refAttr + ']').forEach(e => e.removeAttribute(refAttr));
  const selector = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary',
    '[role=button]', '[role=link]', '[role=textbox]', '[role=combobox]',
    '[role=checkbox]', '[role=radio]', '[role=menuitem]', '[role=option]',
    '[role=tab]', '[role=switch]', '[contenteditable=true]', '[onclick]', '[tabindex]',
    // Bootstrap / Angular UI menus: an <a> without href that opens a submenu
    '.dropdown-toggle', '[dropdown-toggle]', '[data-toggle=dropdown]', '[aria-haspopup]'
  ].join(',');
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = [];
  const seen = new Set();
  let n = 0;

  const modal = Array.from(document.querySelectorAll('[role=dialog],[aria-modal=true],dialog[open],.p-dialog'))
    .find(m => m.getBoundingClientRect().height > 2);
  const cssVisible = el => (el.checkVisibility
    ? el.checkVisibility({ checkVisibilityCSS: true, checkOpacity: false })
    : true);

  const textOf = e => (e ? (e.innerText || e.textContent || '') : '').trim().replace(/\s+/g, ' ');
  const isToggle = el => (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio'))
    || ['checkbox', 'radio', 'switch'].includes(el.getAttribute('role'));
  const isDate = el => el.tagName === 'INPUT' && (
    el.type === 'date'
    || el.getAttribute('aria-haspopup') === 'dialog'
    || !!el.closest('.p-datepicker, .p-calendar, [data-pc-name=datepicker], [data-pc-name=calendar]'));
  const isField = el => ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) || el.getAttribute('role') === 'combobox';
  const labelTarget = id => {
    try { return id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : null; } catch (e) { return null; }
  };

  // Accessible name: aria, <label for>, enclosing <label>, the label of the field's block,
  // the placeholder, then (for a bare checkbox in a table) its column and row headers.
  const labelFor = el => {
    let label = el.getAttribute('aria-label') || '';
    const by = el.getAttribute('aria-labelledby');
    if (!label && by) label = by.split(/\s+/).map(id => textOf(document.getElementById(id))).filter(Boolean).join(' ');
    if (!label && labelTarget(el.id)) label = textOf(labelTarget(el.id));
    if (!label) {
      const enclosing = el.closest('label');
      if (enclosing) label = textOf(enclosing);
    }
    if (!label && isField(el) && !isToggle(el)) {
      // Component libraries often put the id on a wrapper, not on the real <input>
      // (<label for="end"> + <Calendar id="end">): follow it upwards.
      for (let a = el.parentElement, d = 0; a && d < 4 && !label; a = a.parentElement, d++) {
        if (labelTarget(a.id)) label = textOf(labelTarget(a.id));
      }
      // Otherwise: the <label> of the smallest block that holds this field and no other.
      for (let a = el.parentElement, d = 0; a && a !== document.body && d < 4 && !label; a = a.parentElement, d++) {
        if (a.querySelectorAll('input:not([type=hidden]), select, textarea').length > 1) break;
        const l = a.querySelector('label');
        if (l && !l.contains(el)) label = textOf(l);
      }
    }
    // A placeholder is a hint ("Pick a date"), a label names the field ("End date"):
    // keep both, so either wording in a scenario finds it.
    const placeholder = el.getAttribute('placeholder') || '';
    if (placeholder && !label.includes(placeholder)) label = label ? label + ' (' + placeholder + ')' : placeholder;
    if (!label) label = el.getAttribute('title') || '';
    if (!label && isToggle(el)) {
      const wrap = el.closest('.p-radiobutton, .p-checkbox, [data-pc-name=radiobutton], [data-pc-name=checkbox]') || el;
      const next = wrap.nextElementSibling, prev = wrap.previousElementSibling;
      if (next && next.tagName === 'LABEL') label = textOf(next);
      if (!label && prev && prev.tagName === 'LABEL') label = textOf(prev);
    }
    if (!label && isToggle(el)) {
      const cell = el.closest('td,th');
      const row = cell && cell.closest('tr');
      if (cell && row) {
        const index = Array.from(row.children).indexOf(cell);
        const rowHead = row.querySelector('th') || row.children[0];
        const rowLabel = rowHead && rowHead !== cell ? textOf(rowHead) : '';
        const table = row.closest('table');
        const head = table && table.querySelector('thead tr');
        const colLabel = head && head.children[index] ? textOf(head.children[index]) : '';
        label = [colLabel, rowLabel].filter(Boolean).join(' / ');
      }
    }
    if (!label) label = el.getAttribute('name') || el.getAttribute('alt') || '';
    return label.trim().slice(0, 80);
  };

  for (const el of document.querySelectorAll(selector)) {
    if (seen.has(el)) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || el.disabled) continue;
    const toggle = isToggle(el);
    let r = el.getBoundingClientRect();
    if (parseFloat(style.opacity) === 0) {
      // Invisible native input over a styled box (common in component libraries): keep it, use the box.
      if (!toggle || !el.parentElement) continue;
      const parentStyle = window.getComputedStyle(el.parentElement);
      if (parentStyle.display === 'none' || parentStyle.visibility === 'hidden') continue;
      r = el.parentElement.getBoundingClientRect();
    }
    if (r.width < 2 || r.height < 2) continue;
    const onScreen = r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
    if (!onScreen) {
      // Off screen: reachable by scrolling unless a modal is open. elementFromPoint cannot judge
      // it, so CSS visibility and hidden containers decide. (Never apply these filters to what
      // is on screen: elementFromPoint settles that, and an over-eager filter once made a whole
      // side menu disappear.)
      if (modal || !cssVisible(el) || el.closest('[aria-hidden=true],[inert]')) continue;
    } else {
      // On screen: skip what an overlay covers (cookie banner, modal).
      const cx = Math.min(Math.max(r.left + r.width / 2, 0), vw - 1);
      const cy = Math.min(Math.max(r.top + r.height / 2, 0), vh - 1);
      const top = document.elementFromPoint(cx, cy);
      // (a hidden checkbox input is covered by its own styled box: accept it)
      if (top && !el.contains(top) && !top.contains(el)
          && !(toggle && el.parentElement && el.parentElement.contains(top))) continue;
    }
    seen.add(el);
    n += 1;
    el.setAttribute(refAttr, String(n));
    const text = (el.tagName === 'SELECT'
      ? (el.selectedOptions[0] ? el.selectedOptions[0].text : '')
      : (el.innerText || '')).trim().replace(/\s+/g, ' ').slice(0, 80);
    const editable = (el.tagName === 'INPUT' && !toggle && el.type !== 'password') || el.tagName === 'TEXTAREA';
    const expanded = el.getAttribute('aria-expanded');
    const isRadio = el.type === 'radio' || el.getAttribute('role') === 'radio';
    out.push({
      ref: n,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      text: text,
      label: labelFor(el),
      href: el.tagName === 'A' ? (el.getAttribute('href') || '').slice(0, 100) : '',
      options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.text.trim()).slice(0, 20) : [],
      box: [Math.max(r.left, 0), Math.max(r.top, 0), Math.min(r.right, vw), Math.min(r.bottom, vh)],
      off: onScreen ? '' : (r.top >= vh ? 'below' : 'above'),
      onScreen: onScreen,
      value: editable ? String(el.value || '').slice(0, 60) : '',
      checked: toggle ? (el.checked === true || el.getAttribute('aria-checked') === 'true') : null,
      expanded: expanded === null ? '' : expanded,
      kind: isDate(el) ? 'date' : (toggle ? (isRadio ? 'radio' : 'checkbox') : ''),
    });
  }
  // Very long pages (big tables): every on-screen element, then off-screen ones up to the cap.
  if (out.length > maxElements) {
    const keep = new Set();
    for (const e of out) { if (keep.size >= maxElements) break; if (e.onScreen) keep.add(e.ref); }
    for (const e of out) { if (keep.size >= maxElements) break; keep.add(e.ref); }
    return { elements: out.filter(e => keep.has(e.ref)), truncated: out.length - keep.size };
  }
  return { elements: out, truncated: 0 };
}
