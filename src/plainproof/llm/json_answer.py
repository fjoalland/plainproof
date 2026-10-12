"""Reading the JSON object in a model answer, whatever the model wrapped around it."""

from __future__ import annotations

import json
import re
from typing import Any

_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
_FENCED_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BRACES_RE = re.compile(r"\{.*\}", re.DOTALL)


def _as_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return None


def parse_json_object(raw: str) -> dict[str, Any]:
    """The JSON object of an answer: plain, fenced in a code block, or surrounded by prose.

    Reasoning blocks (``<think>...</think>``, printed by some local models) are ignored.
    Raises ``ValueError`` when no object can be read.
    """
    text = _THINK_RE.sub("", raw or "").strip()
    candidates = [text]
    candidates += [m.group(1) for m in _FENCED_RE.finditer(text)]
    candidates += [m.group(0) for m in _BRACES_RE.finditer(text)]
    for candidate in candidates:
        try:
            found = _as_object(json.loads(candidate))
        except json.JSONDecodeError:
            continue
        if found is not None:
            return found
    raise ValueError(f"The model answer contains no JSON object: {text[:200]!r}")
