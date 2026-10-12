// Visible text of the page plus its accessibility labels (aria-label, title, alt, placeholder)
// and, unless withValues is false, the values of its text fields. Never a password, a hidden
// field (tokens the user never sees) nor the "on" of a checkbox or radio button.
(withValues) => {
  const TEXT_TYPES = ['', 'text', 'email', 'number', 'search', 'tel', 'url', 'date', 'datetime-local', 'month',
    'time', 'week'];
  const parts = [];
  if (document.body) {
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll('script, style, noscript, template').forEach(e => e.remove());
    document.body.appendChild(clone);  // innerText needs layout
    clone.style.cssText = 'position:absolute;left:-99999px;top:0;';
    parts.push(clone.innerText || '');
    clone.remove();
  }
  for (const el of document.querySelectorAll('[aria-label],[title],[alt],[placeholder]')) {
    for (const name of ['aria-label', 'title', 'alt', 'placeholder']) {
      const value = el.getAttribute(name);
      if (value) parts.push(value);
    }
  }
  if (withValues !== false) {
    for (const el of document.querySelectorAll('input,textarea')) {
      const textual = el.tagName === 'TEXTAREA' || TEXT_TYPES.includes((el.getAttribute('type') || '').toLowerCase());
      if (el.value && textual) parts.push(el.value);
    }
  }
  return parts.join('\n');
}
