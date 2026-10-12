"""A model that answers from a script: for tests, demos and checking a setup offline.

    plainproof run "Open the app" --model scripted:answers.json

``answers.json`` is a JSON list; each item is one answer (an object, or a string returned as is).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..errors import ConfigError
from .base import ChatRequest, Completion, LLMError, TokenUsage


class ScriptedClient:
    """Returns the scripted answers in order and records every request it receives."""

    def __init__(
        self,
        answers: Sequence[str | Mapping[str, Any]],
        *,
        name: str = "scripted:test",
        vision: bool = True,
        usage: TokenUsage | None = None,
        repeat_last: bool = False,
    ) -> None:
        self._answers = [a if isinstance(a, str) else json.dumps(a, ensure_ascii=False) for a in answers]
        self._name = name
        self._vision = vision
        self._usage = usage if usage is not None else TokenUsage(input_tokens=1000, output_tokens=50)
        self._repeat_last = repeat_last
        self.requests: list[ChatRequest] = []

    @classmethod
    def from_file(cls, path: Path) -> ScriptedClient:
        try:
            answers = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise ConfigError(f"Cannot read the scripted answers {path}: {err}") from None
        if not isinstance(answers, list):
            raise ConfigError(f"{path}: expected a JSON list of answers")
        return cls(answers, name=f"scripted:{path.name}")

    @property
    def name(self) -> str:
        return self._name

    @property
    def vision(self) -> bool:
        return self._vision

    @property
    def remaining(self) -> int:
        return max(len(self._answers) - len(self.requests), 0)

    def complete(self, request: ChatRequest) -> Completion:
        index = len(self.requests)
        self.requests.append(request)
        if index >= len(self._answers):
            if not (self._repeat_last and self._answers):
                raise LLMError("The scripted model has no answer left")
            index = len(self._answers) - 1
        return Completion(text=self._answers[index], usage=self._usage, model=self._name)

    def user_texts(self) -> list[str]:
        """The text the model received at each call (handy in tests)."""
        texts = []
        for request in self.requests:
            parts = [p for m in request.messages for p in m.parts]
            texts.append("\n".join(getattr(p, "text", "") for p in parts if hasattr(p, "text")))
        return texts
