// Text of the table row (or list item) holding each numbered element: {number: row text}.
// A button repeated on every row ("Delete") is told apart by its row when a recording is replayed.
(args) => {
  const out = {};
  document.querySelectorAll('[' + args.attr + ']').forEach(el => {
    const row = el.closest('tr, [role="row"], li');
    if (row) out[el.getAttribute(args.attr)] = (row.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 300);
  });
  return out;
}
