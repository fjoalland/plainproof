"""A scripted HTTP server for provider tests: records requests, answers from a list."""

from __future__ import annotations

import json
from typing import Any

import httpx


class NetworkDown:
    """Placeholder answer: the connection fails."""


class FakeServer:
    def __init__(self, *answers: httpx.Response | NetworkDown) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, NetworkDown):
            raise httpx.ConnectError("connection refused", request=request)
        return answer

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)


def ok(payload: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(200, json=payload, headers=headers)


def error(status: int, message: str = "error", headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message}}, headers=headers)
