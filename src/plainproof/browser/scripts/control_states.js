// State of the visible form controls, for verifications judged on meaning: no text on the
// page says which box is ticked, which option a list shows, or that a button is disabled.
() => {
  const txt = e => (e ? (e.innerText || e.textContent || '') : '').trim().replace(/\s+/g, ' ');
  const visible = el => !el.checkVisibility || el.checkVisibility({ checkVisibilityCSS: true, checkOpacity: false })
    || (el.parentElement && el.parentElement.checkVisibility && el.parentElement.checkVisibility({ checkVisibilityCSS: true }));
  const nameOf = el => {
    let name = el.getAttribute('aria-label') || '';
    if (!name && el.labels && el.labels.length) name = txt(el.labels[0]);
    if (!name && el.parentElement && el.parentElement.tagName === 'LABEL') name = txt(el.parentElement);
    if (!name && el.nextSibling && el.nextSibling.nodeType === 3) name = el.nextSibling.textContent.trim();
    if (!name && el.previousSibling && el.previousSibling.nodeType === 3) name = el.previousSibling.textContent.trim();
    return (name || el.name || el.id || '').slice(0, 80);
  };
  const disabled = el => (el.disabled ? ' (disabled)' : '');
  const out = [];
  for (const el of document.querySelectorAll('input[type=checkbox], input[type=radio], [role=checkbox], [role=radio], [role=switch]')) {
    if (!visible(el)) continue;
    const on = el.checked === true || el.getAttribute('aria-checked') === 'true';
    const kind = (el.type || el.getAttribute('role') || '').toLowerCase();
    out.push(`${kind} "${nameOf(el)}": ${on ? 'checked' : 'not checked'}${disabled(el)}`);
  }
  for (const el of document.querySelectorAll('select')) {
    if (!visible(el)) continue;
    const option = el.selectedOptions && el.selectedOptions[0];
    out.push(`list "${nameOf(el)}": shows "${option ? option.text.trim() : ''}"${disabled(el)}`);
  }
  for (const el of document.querySelectorAll('input:not([type]), input[type=text], input[type=email], input[type=number], input[type=search], input[type=tel], input[type=date], textarea')) {
    if (!visible(el)) continue;
    out.push(`field "${nameOf(el) || el.getAttribute('placeholder') || ''}": "${String(el.value || '').slice(0, 80)}"${disabled(el)}`);
  }
  // Disabled buttons are left out of the element list (they cannot be clicked): they are
  // listed here, or "the Save button is disabled" could only be "proved" by the word Save.
  // Toolbar buttons of rich-text editors (disabled until the editor has focus) are skipped:
  // a few editors on one form would bury the Save button under a hundred lines.
  const buttons = new Set();
  for (const el of document.querySelectorAll('button, input[type=submit], input[type=button], [role=button]')) {
    if (!visible(el) || !(el.disabled || el.getAttribute('aria-disabled') === 'true')) continue;
    if (el.closest('[role=toolbar], .ta-toolbar, .btn-toolbar, .ql-toolbar, .tox-toolbar, .ck-toolbar')) continue;
    const name = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('title') || '').trim();
    buttons.add(`button "${name.slice(0, 80)}": disabled`);
  }
  return [...buttons, ...out].slice(0, 120);
}
