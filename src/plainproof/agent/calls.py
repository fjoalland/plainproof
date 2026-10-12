"""The agent's model calls: one request, one JSON object back, every call accounted for."""

from __future__ import annotations

from typing import Any

from ..llm.base import ChatRequest, LLMClient
from ..llm.json_answer import parse_json_object
from ..llm.pricing import UsageMeter


class ModelAnswerError(Exception):
    """The model kept answering something that is not a JSON object."""


class ModelCalls:
    """Asks the model, reads its JSON answer, and counts the tokens of every call of a run."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.meter = UsageMeter()

    def ask(self, system: str, text: str, image: bytes | None = None, attempts: int = 2) -> dict[str, Any]:
        """The JSON object answered by the model; an unreadable answer is asked again.

        Network errors, rate limits and overloads are retried by the provider client; an
        :class:`~plainproof.llm.base.LLMError` reaching this point is final.
        """
        request = ChatRequest.single(system, text, image if self.llm.vision else None)
        problem = ""
        for _ in range(max(1, attempts)):
            completion = self.llm.complete(request)
            self.meter.add(completion.usage)  # every answer is billed, usable or not
            try:
                return parse_json_object(completion.text)
            except ValueError as err:
                problem = str(err)
        raise ModelAnswerError(problem)
