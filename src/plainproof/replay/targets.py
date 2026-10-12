"""Describing an element so that it can be found again without its number.

Element numbers change at every observation, so a recording describes each target by what
it is (tag, role, type, label, text), its rank among the elements that look the same, and,
in a table, the text of its row: a "Delete" button repeated on every row is told apart by
its row, not by an identifier that changes each time the data is created again.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from typing import Any

from ..browser.model import Element
from ..text import normalize

_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")

Target = dict[str, Any]


def masked(text: str) -> str:
    """Normalised, numbers replaced by #: "Delete order 61" and "Delete order 63" look the same."""
    return re.sub(r"\d+", "#", normalize(text))


def _signature(element: Element, mask: bool = False) -> tuple[str, ...]:
    shape = masked if mask else normalize
    return element.tag, element.role, element.type, shape(element.label), shape(element.text)


def _target_signature(target: Mapping[str, Any], mask: bool = False) -> tuple[str, ...]:
    shape = masked if mask else normalize
    return (
        str(target.get("tag", "")),
        str(target.get("role", "")),
        str(target.get("type", "")),
        shape(str(target.get("label", ""))),
        shape(str(target.get("text", ""))),
    )


def target_name(target: Mapping[str, Any]) -> str:
    return str(target.get("label") or target.get("text") or "").strip()


def target_of(element: Element, elements: Sequence[Element], rows: Mapping[str, str] | None = None) -> Target:
    """A stable description of ``element`` among the ``elements`` of its page."""
    same = [e for e in elements if _signature(e) == _signature(element)]
    target: Target = {
        "tag": element.tag,
        "role": element.role,
        "type": element.type,
        "kind": element.kind,
        "label": element.label,
        "text": element.text,
        "nth": same.index(element) if element in same else 0,
    }
    row = (rows or {}).get(str(element.ref), "")
    if row:
        target["row"] = row
    if element.checked is not None:
        target["checked"] = element.checked  # checked again before replaying the action
    return target


def same_row(recorded: str, current: str) -> bool:
    """The same line of a table: every date of the recorded row is in it, and the rest of its text is
    close (identifiers may differ: the data was created again; cells may come back in another order)."""
    dates = _DATE_RE.findall(recorded)
    if dates and not all(d in current for d in dates):
        return False
    if SequenceMatcher(None, masked(recorded), masked(current)).ratio() >= 0.8:
        return True
    before, after = Counter(masked(recorded).split()), Counter(masked(current).split())
    total = max(sum(before.values()), sum(after.values()))
    return bool(total) and sum((before & after).values()) / total >= 0.9


def find_target(
    target: Mapping[str, Any], elements: Sequence[Element], rows: Mapping[str, str] | None = None
) -> Element | None:
    """The element of the page that matches the recorded one, or None. In a table, the row decides
    and exactly one candidate row must match: otherwise nothing is returned, and nothing is clicked."""
    exact = [e for e in elements if _signature(e) == _target_signature(target)]
    row = target.get("row")
    if row and rows is not None:
        pool = exact or [e for e in elements if _signature(e, mask=True) == _target_signature(target, mask=True)]
        matching = [e for e in pool if same_row(str(row), rows.get(str(e.ref), ""))]
        return matching[0] if len(matching) == 1 else None
    nth = int(target.get("nth", 0))
    return exact[nth] if nth < len(exact) else None
