"""Recording the actions of a run with a model, to replay them later without one.

Every action that succeeds is recorded with a stable description of its target instead of
its number. A verification judged on meaning is recorded as the quote the judge had to find
on the page. Secrets stay ``${PLACEHOLDERS}``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..agent.actions import TARGETED, Outcome, as_ref
from ..browser.model import Observation
from ..secrets import Secrets
from ..text import truthy
from .targets import target_of

FORMAT_VERSION = 1
# The element really acted on, from the browser's sentence (it may have been redirected by label).
_ACTED_ON_RE = re.compile(r"\b(?:Clicked|into|in) \[(\d+)\]")


class Recorder:
    """Collects the replayable actions of one run; :meth:`data` is the recording."""

    def __init__(self, secrets: Secrets | None = None) -> None:
        self.secrets = secrets or Secrets()
        self.steps: list[dict[str, Any]] = []
        self.start_url = ""

    def start(self, url: str) -> None:
        """The first page of the run, where a replay starts."""
        if not self.start_url:
            self.start_url = url

    def _placeholder(self, value: str) -> str:
        """Secrets as ${NAME}, whether the model typed the placeholder or the value."""
        return self.secrets.hide(self.secrets.substitute(value))

    def add(
        self,
        action: Mapping[str, Any],
        observation: Observation,
        outcome: Outcome,
        step_no: int = 0,
        rows: Mapping[str, str] | None = None,
    ) -> None:
        """Record a performed action. ``rows`` (see ``row_texts``) must be read before it ran:
        a deletion removes the very row it was clicked in."""
        kind = action.get("action")
        if kind in (None, "finish") or outcome.check is False:
            return
        entry: dict[str, Any] = {"action": kind, "step_no": step_no}
        if kind in TARGETED:
            acted_on = _ACTED_ON_RE.search(outcome.message)
            element = observation.by_ref(int(acted_on.group(1)) if acted_on else as_ref(action.get("ref")))
            if element is None:
                return  # nothing reliable to replay
            entry["target"] = target_of(element, observation.elements, rows)
        if kind == "type":
            entry["text"] = self._placeholder(str(action.get("text", "")))
            entry["submit"] = truthy(action.get("submit"))
        elif kind == "select":
            entry["option"] = self._placeholder(str(action.get("option", "")))
        elif kind == "press":
            entry["key"] = str(action.get("key", "Enter"))
        elif kind == "scroll":
            entry["direction"] = str(action.get("direction", "down"))
        elif kind == "wait":
            entry["seconds"] = float(action.get("seconds", 1))
        elif kind == "navigate":
            entry["url"] = str(action.get("url", ""))
        elif kind == "note":
            entry["note"] = self._placeholder(str(action.get("note", "")))
        elif kind == "check":
            absent = truthy(action.get("absent"))
            entry["absent"] = absent
            if outcome.by_meaning:
                entry["meaning"] = str(action.get("meaning") or action.get("text") or "")
                if outcome.evidence and not absent:
                    entry["text"] = outcome.evidence[:160]  # the proof quoted by the judge
                else:
                    entry["replayable"] = False  # nothing precise to look for without a model
            elif action.get("url"):
                entry["url"] = str(action["url"])
            else:
                entry["text"] = self._placeholder(str(action.get("text", "")))
        self.steps.append(entry)

    def data(self, scenario_name: str, model: str) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "scenario": scenario_name,
            "model": model,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "start_url": self.start_url,
            "steps": self.steps,
        }
