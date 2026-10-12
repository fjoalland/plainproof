"""The actions a model can decide, and the outcome of performing one."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..text import truthy

ACTIONS = ("navigate", "click", "type", "select", "press", "scroll", "wait", "back", "check", "note", "finish")
TARGETED = ("click", "type", "select")
"""Actions aimed at a numbered element."""
_HIDDEN_PARAMS = ("action", "thought", "step", "note")


@dataclass(frozen=True)
class Outcome:
    """What performing an action produced."""

    message: str
    """The sentence the model reads in its history ("Clicked [3] "Save"", "CHECK OK: ...")."""
    check: bool | None = None
    """For a verification: did it pass?"""
    evidence: str | None = None
    """For a verification judged on meaning: the passage of the page that proves it."""
    by_meaning: bool = False


def as_ref(value: object) -> int | None:
    """The element number of an action; None when the model gave none (its label may locate it)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):
        return None


def check_fragment(action: Mapping[str, Any]) -> str:
    """What a check looks for: a URL fragment, a text, or an expectation in words."""
    return str(action.get("url") or action.get("text") or action.get("meaning") or "")


def check_key(action: Mapping[str, Any]) -> tuple[str, bool] | None:
    """Identity of a check (what it looks for, and whether for an absence), to count identical failures."""
    if action.get("action") != "check":
        return None
    return check_fragment(action), truthy(action.get("absent"))


def short_params(action: Mapping[str, Any]) -> str:
    return " ".join(f"{key}={value!r}" for key, value in action.items() if key not in _HIDDEN_PARAMS)


def signature(action: Mapping[str, Any], drop: tuple[str, ...] = ("thought",)) -> str:
    """A comparable form of an action."""
    return json.dumps({k: v for k, v in action.items() if k not in drop}, sort_keys=True, ensure_ascii=False)


def banner(action: Mapping[str, Any]) -> str:
    """A one-line description of an action, drawn on its screenshot."""
    kind = str(action.get("action", "?"))
    if kind == "click":
        return f"CLICK [{action.get('ref')}]"
    if kind == "type":
        return f'TYPE [{action.get("ref")}] "{action.get("text", "")}"' + (
            "  + Enter" if truthy(action.get("submit")) else ""
        )
    if kind == "select":
        return f'SELECT [{action.get("ref")}] "{action.get("option", "")}"'
    if kind == "navigate":
        return f"NAVIGATE {action.get('url', '')}"
    if kind == "check":
        return f"CHECK {check_fragment(action)!r}"
    if kind == "finish":
        return "FINISH " + ("PASS" if truthy(action.get("success")) else "FAIL")
    return f"{kind.upper()} {short_params(action)}".strip()
