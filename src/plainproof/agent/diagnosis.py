"""After a failure, one more model call explains it in plain language, with its probable cause."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..results import Diagnosis, Step
from ..secrets import Secrets
from .progress import history_text, numbered


def diagnosis_request_text(lines: Sequence[str], history: Sequence[Step], reason: str) -> str:
    return (
        f"TEST SCENARIO:\n{numbered(lines)}\n\n"
        f"ACTION HISTORY:\n{history_text(history)}\n\n"
        f"RUN STOPPED BECAUSE: {reason or '-'}\n\n"
        "Explain the failure. Answer with a single JSON object."
    )


def read_diagnosis(answer: Any, secrets: Secrets) -> Diagnosis | None:
    """The validated explanation, or None when the answer has none (it never fails the run)."""
    diagnosis = Diagnosis.from_dict(answer if isinstance(answer, dict) else None)
    if diagnosis is None:
        return None
    return Diagnosis(
        summary=secrets.hide(diagnosis.summary), cause=diagnosis.cause, details=secrets.hide(diagnosis.details)
    )
