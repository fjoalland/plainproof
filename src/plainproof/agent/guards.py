"""Deterministic guards between the model and the verdict.

The model decides; these functions decide whether to believe it. Each one answers a failure,
or a false success, observed on a real application:

- a success verdict is refused when a check failed, a verification was skipped, or the
  scenario was not carried out to the end;
- a check only proves a verification step when it looks for one of the step's exact values,
  or judges the step's own wording (never a weaker rephrasing);
- loops (the same action again and again, scrolling up and down, circling one step) end the
  run instead of burning the whole budget.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..i18n import t
from ..lexicon import asks_verification
from ..results import PlanStep, Step
from ..text import anchor_hit, anchors, squash, truthy
from .actions import check_fragment, signature

_IDLE = {"scroll", "wait", "back"}
_IDEMPOTENT = {"check", "type", "note"}
"""Actions that change nothing when repeated after a success."""


# -- loops ------------------------------------------------------------------------------------
def scroll_tail(steps: Sequence[Step]) -> int:
    """Consecutive scrolls at the end of the history."""
    count = 0
    for s in reversed(steps):
        if s.kind != "scroll":
            break
        count += 1
    return count


def failed_checks_tail(steps: Sequence[Step]) -> int:
    """Consecutive failed checks at the end of the history."""
    count = 0
    for s in reversed(steps):
        if not (s.kind == "check" and s.failed_check):
            break
        count += 1
    return count


def repeated_tail(steps: Sequence[Step]) -> int:
    """Consecutive actions at the end of the history that repeat the same action AND got the
    same outcome. A menu clicked open, closed, open is not a loop (its outcome alternates);
    the same failed check four times is."""

    def key(s: Step) -> tuple[str, str]:
        return signature(s.action), s.outcome[:120]

    if not steps:
        return 0
    last, count = key(steps[-1]), 0
    for s in reversed(steps):
        if key(s) != last:
            break
        count += 1
    return count


def sterile_tail(steps: Sequence[Step], window: int = 8) -> bool:
    """True when the last ``window`` actions changed nothing: only scrolls, waits and checks,
    at most two distinct ones, on the same page. This is the up/down oscillation that burned
    whole budgets while the repetition detector never fired (the actions alternate)."""
    tail = steps[-window:]
    if len(tail) < window:
        return False
    if any(s.kind not in _IDLE | {"check"} for s in tail):
        return False
    if any(s.url_after and s.url_after != s.url for s in tail):
        return False
    return len({signature(s.action, drop=("thought", "step", "note")) for s in tail}) <= 2


def stalled_on_step(steps: Sequence[Step], total: int, window: int = 12) -> bool:
    """True when ``window`` actions in a row did not move past the same step. Circling one step
    keeps the other detectors quiet (the actions all differ) while burning the budget."""
    if total <= 1 or len(steps) < window:
        return False
    current = steps[-1].step_no
    if current <= 0 or current >= total:  # on the last step, let it conclude
        return False
    return all(s.step_no == current for s in steps[-window:])


# -- redundant actions ----------------------------------------------------------------------
def already_succeeded(action: Mapping[str, Any], steps: Sequence[Step], step_no: int) -> Step | None:
    """The earlier action that already did exactly this, successfully, for the same step.

    Seen with real models: "step 5 is done, moving on" in the reasoning, yet the same
    successful check for step 5, over and over. Clicks are never redundant: a toggle menu
    legitimately needs a second click.
    """
    if action.get("action") not in _IDEMPOTENT or step_no <= 0:
        return None

    def comparable(a: Mapping[str, Any]) -> str:
        keep = {k: v for k, v in a.items() if k not in ("thought", "step", "note", "label")}
        if a.get("action") == "note":
            keep["note"] = a.get("note")
        if "absent" in keep:
            keep["absent"] = truthy(keep["absent"])
        return json.dumps(keep, sort_keys=True, ensure_ascii=False)

    wanted = comparable(action)
    for s in steps:
        if s.step_no != step_no or s.error or s.failed_check or "WARNING" in s.result:
            continue
        if comparable(s.action) == wanted:
            return s
    return None


# -- verifications --------------------------------------------------------------------------
def needs_check(lines: Sequence[str], verify_flags: Sequence[bool] | None, n: int) -> bool:
    """Does step ``n`` ask for a verification? The interpretation says so; without one, the wording."""
    if verify_flags is not None and 1 <= n <= len(verify_flags):
        return verify_flags[n - 1]
    return 1 <= n <= len(lines) and asks_verification(lines[n - 1])


def unverified_steps(lines: Sequence[str], steps: Sequence[Step], verify_flags: Sequence[bool] | None) -> list[int]:
    """Verification steps for which no check was made. With a plan, only checks that prove their
    step count. A green run that verified nothing is worse than a red one."""
    if verify_flags is not None:
        checked = {s.step_no for s in steps if s.proof}
    else:
        checked = {s.step_no for s in steps if s.kind == "check"}
    return [n for n in range(1, len(lines) + 1) if needs_check(lines, verify_flags, n) and n not in checked]


def verdict_objection(lines: Sequence[str], steps: Sequence[Step], verify_flags: Sequence[bool] | None) -> str | None:
    """Why a success verdict must be refused, or None when it can be accepted."""
    if verify_flags is not None:
        for n, needed in enumerate(verify_flags, 1):
            if not needed:
                continue
            proofs = [s for s in steps if s.step_no == n and s.proof]
            if proofs and proofs[-1].failed_check:
                return t("reason.finish_rejected_check", check=check_fragment(proofs[-1].action))
            # Each exact value of the step stands on its own: the expected message failed every
            # check, then the dialog's title (another value of the same step) passed for it all.
            for value in anchors(lines[n - 1]) if n <= len(lines) else []:
                if value.startswith("${") or not squash(value):
                    continue
                about = [
                    s
                    for s in proofs
                    if s.action.get("meaning") or squash(value) in squash(str(s.action.get("text") or ""))
                ]
                if about and about[-1].failed_check:
                    return t("reason.finish_rejected_check", check=value)
    checks = [s for s in steps if s.kind == "check"]
    if checks:
        if checks[-1].failed_check:
            return t("reason.finish_rejected_check", check=check_fragment(checks[-1].action))
    elif any(needs_check(lines, verify_flags, n) for n in range(1, len(lines) + 1)):
        return t("reason.finish_rejected_no_check")
    # Only enforced when the model numbers its steps: one that ignores the field is not punished.
    reached = max((s.step_no for s in steps), default=0)
    if lines and reached and reached < len(lines):
        return t("reason.finish_rejected_steps", done=reached, total=len(lines))
    if reached:
        missing = unverified_steps(lines, steps, verify_flags)
        if missing:
            return t("reason.finish_rejected_unverified", steps=", ".join(str(n) for n in missing))
    return None


def bind_check(action: dict[str, Any], spec: PlanStep, n: int) -> tuple[dict[str, Any], bool, str]:
    """Tie a check to verification step ``n``: (action to run, proves the step?, note for the model).

    Seen on a real run: the expected message was missing (a real defect), the judge said so,
    and the agent rephrased its expectation ("an error is shown", then "nothing was created")
    until one passed. The expectation is not the agent's to rewrite: a meaning check always
    judges the step's own wording, and a text check proves the step only when it looks for
    one of its exact values (or a passage of four words or more of the expectation).
    """
    if action.get("meaning"):
        return {**action, "meaning": spec.text, "absent": spec.absent}, True, ""
    values = anchors(spec.text)
    text = str(action.get("text") or "")
    fragment = squash(text or str(action.get("url") or ""))
    if text and any(squash(v) and squash(v) in fragment for v in values):
        return {**action, "absent": spec.absent}, True, ""
    if text and len(text.split()) >= 4 and fragment and fragment in squash(spec.text):
        return {**action, "absent": spec.absent}, True, ""
    if values:
        hint = (
            "one of its exact values ("
            + ", ".join(f'"{v}"' for v in values[:5])
            + ') with "text", or a "meaning" check'
        )
    else:
        hint = 'a "meaning" check: it names no exact text to look for'
    return action, False, f' (NOTE: this does not prove step {n} "{spec.text}". Prove it with {hint}.)'


def realign_step(action: Mapping[str, Any], current: int, plan: Sequence[PlanStep], history: Sequence[Step]) -> int:
    """Correct a step number that lags one behind, using the plan.

    Models often number the first action of a step with the previous step's number. The
    progress then says the action is still to do, and the model repeats it until the loop
    guard stops the run.
    """
    if not 1 <= current < len(plan):
        return current
    here, ahead = plan[current - 1], plan[current]
    kind = action.get("action")
    if kind in ("click", "type", "select"):
        target = squash(" ".join(str(action.get(k) or "") for k in ("label", "text", "option")))
        if target and anchor_hit(ahead.text, target) and not anchor_hit(here.text, target):
            return current + 1
    elif (
        kind == "check"
        and not here.verify
        and ahead.verify
        and any(s.step_no == current and s.kind != "check" for s in history)
    ):
        return current + 1  # a verification made right after the action step it follows
    return current
