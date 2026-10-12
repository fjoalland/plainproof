"""What the model is reminded of at every turn.

Only the step it reached, its notes and a one-line history of its actions survive from one
turn to the next; its reasoning does not. Without this, agents restarted scenarios from the
middle, or skipped the second half of steps like "click X and verify Y".
"""

from __future__ import annotations

from collections.abc import Sequence

from ..results import Step
from .actions import short_params


def numbered(lines: Sequence[str]) -> str:
    return "\n".join(f"{n}. {line}" for n, line in enumerate(lines, 1))


def history_text(history: Sequence[Step]) -> str:
    """One line per action: what was done, what came of it, and the page it led to."""
    return (
        "\n".join(
            f"{s.index}. "
            + (f"[step {s.step_no}] " if s.step_no else "")
            + f"{s.kind} {short_params(s.action)} -> {s.outcome}"
            + (f"  -> page: {s.url_after}" if s.url_after and s.url_after != s.url else "")
            for s in history
        )
        or "(no action yet)"
    )


def progress_text(
    lines: Sequence[str], current: int, history: Sequence[Step], notes: Sequence[str], source_line: str = ""
) -> str:
    """Where the model stands in the scenario.

    ``current`` is the step the last actions belonged to: it may be only half done (a click
    made, its verification still missing), so it is never presented as finished.
    """
    total = len(lines)
    if current <= 0:
        out = [f"No step done yet. Start with step 1 of {total}: {lines[0] if lines else ''}"]
    else:
        out = []
        if current > 1:
            out.append(f"Steps 1 to {current - 1} of {total} are done: NEVER redo them.")
        out.append(f"CURRENT STEP {current} of {total}: {lines[current - 1]}")
        if source_line:
            # The interpretation may lose a nuance ("even if the field refuses it, do not retry"):
            # the author's own sentence stays in front of the agent.
            out.append(f'  written by the scenario author as: "{source_line}"')
        done = [
            f"{s.kind} {short_params(s.action)}".strip()
            + (" (ERROR)" if s.error else " (CHECK FAILED)" if s.failed_check else "")
            for s in history
            if s.step_no == current
        ]
        out.append(f"Actions already made for step {current}: " + ("; ".join(done) or "none"))
        if current < total:
            out.append(
                f"NEXT STEP {current + 1}: {lines[current]}\n"
                f"Your next action is EITHER the part of step {current} still missing from the actions above, "
                f'OR, when nothing is missing, the first action of step {current + 1} with "step": {current + 1}. '
                "Never repeat an action that already succeeded: if you think a step is done, you must move on."
            )
        else:
            out.append("This is the last step: once it is fully done and its checks are OK, finish.")
    if notes:
        out.append("NOTES YOU WROTE (facts read on the page, use them as they are):")
        out += [f"  - {note}" for note in notes]
    return "\n".join(out)
