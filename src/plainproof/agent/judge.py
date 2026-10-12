"""Verifications described in words, judged by a separate model call on the page text.

The judge may read the page; it may not imagine it. A positive verdict is accepted only when
the passage it quotes really is on the page, is long enough to say something, was not typed
there by the agent itself, and when every exact wording the expectation names is on the page.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..lexicon import says_absent
from ..text import anchors, labels, squash, truthy
from .actions import Outcome

PAGE_TEXT_LIMIT = 15000


def judge_request_text(expectation: str, absent: bool, url: str, page_text: str) -> str:
    return (
        f"EXPECTED RESULT{' (must NOT be shown)' if absent else ''}: {expectation}\n\n"
        f"CURRENT PAGE: {url}\n\n"
        "PAGE TEXT (visible text, accessibility labels, state of the form controls, "
        "notifications shown since the last action):\n"
        f"{page_text[:PAGE_TEXT_LIMIT]}\n\nAnswer with a single JSON object."
    )


def evaluate_judgement(
    answer: Mapping[str, Any],
    expectation: str,
    absent: bool,
    page_text: str,
    only_in_typed_fields: Callable[[str], bool],
) -> Outcome:
    """The verdict of a meaning check, after the judge's answer has been checked against the page."""
    satisfied = truthy(answer.get("satisfied"))
    evidence = " ".join(str(answer.get("evidence") or "").split())
    why = str(answer.get("explanation") or "").strip()

    def failed(reason: str) -> Outcome:
        return Outcome(f'CHECK FAILED (by meaning): "{expectation}". {reason}'.strip(), check=False, by_meaning=True)

    if not satisfied:
        return failed(why)
    if absent:
        return Outcome(f'CHECK OK (by meaning): "{expectation}". {why}'.strip(), check=True, by_meaning=True)
    page = squash(page_text)
    # A quote must say something: "on" is on every page and once "proved" that a box was ticked.
    if len(squash(evidence)) < 5 or squash(evidence) not in page:
        return failed("The judge found it but could not quote the page, so the verdict is not accepted.")
    if only_in_typed_fields(evidence):
        return failed("The quote is only in a field you typed it into yourself, which proves nothing.")
    # Every exact wording of the step must be on the page: seen in a real run, the step expected
    # one confirmation message, the judge accepted the real, different one on a retry, and a
    # test meant to fail passed. Same for the labels it names, except in a negative sentence
    # ("there is no Statistics menu" names a label that must NOT be there).
    missing = [a for a in anchors(expectation) if not a.startswith("${") and squash(a) and squash(a) not in page]
    if not says_absent(expectation):
        missing += [label for label in labels(expectation) if squash(label) not in page]
    if missing:
        return failed(
            f'"{missing[0]}" is not on the page: an exact wording of the step cannot be replaced by another one.'
        )
    quote = evidence[:200]
    return Outcome(
        f'CHECK OK (by meaning): "{expectation}". The page shows: "{quote}"',
        check=True,
        evidence=quote,
        by_meaning=True,
    )
