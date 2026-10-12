"""Finding what the model meant, among the elements of the last observation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from ..text import normalize
from .model import Element


class TargetError(ValueError):
    """The element the model aimed at cannot be identified. The message says what exists instead."""

    def __init__(self, message: str, kind: Literal["no_number", "mismatch", "missing"], wanted: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.wanted = wanted


def resolve_target(elements: Mapping[int, Element], ref: int | None, expect: str | None) -> tuple[int, str]:
    """The number to act on, and a note when it differs from the one the model gave.

    Numbers are recomputed at every observation: a list that opens or closes shifts them all,
    and a model reusing the previous turn's number would click whatever took its place. The
    model therefore names its target, and the name is checked before acting. A stale number
    is corrected only toward an element carrying exactly that name; anything else is refused
    with the list of candidates.
    """
    if not expect or not expect.strip():
        if ref is None:
            raise TargetError(
                'No element number given. Answer with "ref": <number from the element list> '
                'and "label": <the label of that element>.',
                kind="no_number",
            )
        return ref, ""
    element = elements.get(ref) if ref is not None else None
    wanted = normalize(expect)

    def matches(e: Element) -> bool:
        hay = normalize(f"{e.label} {e.text}")
        return bool(hay) and (wanted in hay or hay in wanted)

    def exact(e: Element) -> bool:
        return wanted in (normalize(e.label), normalize(e.text), normalize(f"{e.label} {e.text}"))

    if ref is not None and element is not None and matches(element):
        return ref, ""
    candidates = [e for e in elements.values() if matches(e)]
    if len(candidates) == 1 and (exact(candidates[0]) or ref is None):
        found = candidates[0]
        if ref is None:
            return found.ref, f' (no number was given, "{expect}" is [{found.ref}])'
        return found.ref, f' (you asked for [{ref}], but "{expect}" is [{found.ref}]: used that one)'
    if ref is None:
        actually = "No element number was given"
    elif element is not None:
        actually = f'[{ref}] is "{element.name}"'
    else:
        actually = f"[{ref}] is not on the page"
    if candidates:
        numbers = ", ".join(f'[{e.ref}] "{e.name}"' for e in candidates[:5])
        raise TargetError(
            f'{actually}, not "{expect}". Elements matching "{expect}": {numbers}. Use one of those numbers.',
            kind="mismatch",
            wanted=wanted,
        )
    raise TargetError(
        f'{actually}, not "{expect}", and no element on this page carries that label. '
        "Take the number from the current element list, or conclude that it is not on this page.",
        kind="missing",
        wanted=wanted,
    )


def match_option(texts: Sequence[str], wanted: str) -> int | None:
    """Index of the option matching ``wanted``: exact (case and accents ignored), then prefix, then substring."""
    target = normalize(wanted)
    if not target:
        return None
    normalized = [normalize(t) for t in texts]
    for test in (lambda x: x == target, lambda x: x.startswith(target), lambda x: target in x):
        for index, text in enumerate(normalized):
            if test(text):
                return index
    return None
