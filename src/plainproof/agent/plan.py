"""Turning a scenario written in business words into precise steps, and keeping it honest.

One model call reads the scenario with the project context and splits it into steps, each an
action or a verification, tied to the line it comes from. No keyword list can follow how
people write; the model can. But the model may also "fix" a scenario with what the context
says, which would turn a test written to fail into a green one. :func:`clean_plan` refuses
that: an expectation may be made precise, never reversed or emptied of what it names.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..lexicon import says_absent
from ..results import PlanStep
from ..text import named_values, squash, truthy

MAX_STEPS = 80


def plan_request_text(lines: Sequence[str], context: str) -> str:
    return (
        f"APPLICATION CONTEXT:\n{context or '(none)'}\n\n"
        "SCENARIO WRITTEN BY THE BUSINESS USER (numbered lines):\n"
        + "\n".join(f"{n}. {line}" for n, line in enumerate(lines, 1))
        + "\n\nAnswer with a single JSON object."
    )


def clean_plan(answer: Any, lines: Sequence[str]) -> list[PlanStep] | None:
    """The validated plan, or None when the answer is unusable (the run then executes the
    scenario lines as they are)."""
    items = answer.get("steps") if isinstance(answer, dict) else None
    if not isinstance(items, list) or not items or len(items) > MAX_STEPS:
        return None
    plan = []
    for item in items:
        if not isinstance(item, dict):
            return None
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            return None
        try:
            source = max(0, min(int(item.get("source") or 0), len(lines)))
        except (TypeError, ValueError):
            source = 0
        verify = truthy(item.get("verify"))
        absent = verify and truthy(item.get("absent"))
        if absent and 0 < source <= len(lines) and not says_absent(lines[source - 1]):
            # Seen in a real run: "I see a Statistics menu" became "the menu has no Statistics
            # entry" because the context lists the real menus, and a test meant to fail passed.
            # The step keeps the business wording of its line, checked as a presence.
            absent, text = False, lines[source - 1]
        plan.append(PlanStep(text=text, verify=verify, absent=absent, source=source))
    return keep_named_values(plan, lines)


def keep_named_values(plan: list[PlanStep], lines: Sequence[str]) -> list[PlanStep]:
    """A line whose verification lost one of its named values gets a verification of the line itself.

    Seen in a real run: "I can choose between Partners and Users" was planned as "the menu shows
    Partners and Reference policy" (the real entries, known from the context); the step passed
    and a test meant to fail succeeded. The added step is judged on the business wording.
    """
    result = list(plan)
    for n, line in enumerate(lines, 1):
        steps = [s for s in plan if s.source == n]
        if not any(s.verify for s in steps):
            continue
        # A line that negates nothing affirms its values: finding them only in an absence check
        # is a reversal ("there is only one record left: X" seen planned as "X is no longer shown").
        if not says_absent(line):
            steps = [s for s in steps if not s.absent]
        written = squash(" ".join(s.text for s in steps))
        if any(squash(v) and squash(v) not in written for v in named_values(line)):
            last = max(i for i, s in enumerate(result) if s.source == n)
            result.insert(last + 1, PlanStep(text=line, verify=True, absent=False, source=n))
    return result
