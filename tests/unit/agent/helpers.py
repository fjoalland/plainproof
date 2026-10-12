"""Builders shared by the agent tests."""

from __future__ import annotations

from typing import Any

from plainproof.results import Step


def step(
    index: int = 1,
    action: dict[str, Any] | None = None,
    *,
    result: str = "",
    error: str | None = None,
    check: bool | None = None,
    proof: bool | None = None,
    step_no: int = 0,
    url: str = "http://app/#/form",
    url_after: str = "",
) -> Step:
    return Step(
        index=index,
        url=url,
        action=action or {"action": "click", "ref": 1},
        result=result,
        error=error,
        check=check,
        proof=proof,
        step_no=step_no,
        url_after=url_after or url,
    )


def check(text: str, ok: bool, *, index: int = 1, step_no: int = 0, proof: bool | None = None, **extra: Any) -> Step:
    status = "CHECK OK" if ok else "CHECK FAILED"
    return step(
        index,
        {"action": "check", "text": text, **extra},
        result=f'{status}: "{text}"',
        check=ok,
        step_no=step_no,
        proof=proof,
    )
