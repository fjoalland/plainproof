"""Shared machinery of the HTTP provider adapters: retries, back-off and parameter fallbacks.

Adapters talk to the providers' REST APIs directly (no vendor SDK): one dependency (httpx),
the same retry policy everywhere, and request formats that tests can check exactly.

httpx honours the usual environment variables: ``HTTPS_PROXY``, and ``SSL_CERT_FILE`` for a
company certificate authority.
"""

from __future__ import annotations

import base64
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .base import ChatRequest, Completion, ImagePart, LLMError, TokenUsage

# Rate limits, overloads, gateway errors: worth another try.
TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529})
MAX_RETRY_AFTER_S = 60.0


@dataclass(frozen=True)
class OptionalParam:
    """A request parameter that some models or servers reject (``temperature`` on reasoning
    models, JSON mode on some local servers). When a 400 answer names it, it is dropped and
    the request sent again; it stays dropped for the rest of the session."""

    path: tuple[str, ...]
    hints: tuple[str, ...]


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def data_url(part: ImagePart) -> str:
    return f"data:{part.media_type};base64,{b64(part.data)}"


def deep_merge(base: dict[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    """``extra`` merged into ``base``, recursively for nested objects; ``extra`` wins."""
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _pop_path(payload: dict[str, Any], path: tuple[str, ...]) -> bool:
    node: Any = payload
    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
    if isinstance(node, dict) and path[-1] in node:
        del node[path[-1]]
        return True
    return False


def error_message(response: httpx.Response) -> str:
    """The human-readable message of an error answer, whatever its shape."""
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:500] or response.reason_phrase
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:500]
        for value in (err, data.get("message"), data.get("detail")):
            if value:
                return str(value)[:500]
    return str(data)[:500]


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return min(float(response.headers["retry-after"]), MAX_RETRY_AFTER_S)
    except (KeyError, ValueError):
        return None


class HttpClient(ABC):
    """Base of the provider adapters. Subclasses describe the URL, headers, payload and answer."""

    provider = "custom"
    default_base_url = ""
    optional_params: tuple[OptionalParam, ...] = ()

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float | None = 0.1,
        vision: bool = True,
        timeout: float = 120.0,
        max_attempts: int = 4,
        options: Mapping[str, Any] | None = None,
        auth_hint: str = "",
        provider_name: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._api_key = api_key
        self._base_url = (base_url or self.default_base_url).rstrip("/")
        self._vision = vision
        self._max_attempts = max(1, max_attempts)
        self._options = dict(options or {})
        self._auth_hint = auth_hint
        self._provider_name = provider_name or self.provider
        self._sleep = sleep
        self._dropped: set[tuple[str, ...]] = set()
        self._http = httpx.Client(timeout=timeout, transport=transport)

    @property
    def name(self) -> str:
        return f"{self._provider_name}:{self.model}"

    @property
    def vision(self) -> bool:
        return self._vision

    def close(self) -> None:
        self._http.close()

    # -- what each provider describes ------------------------------------------------------
    @abstractmethod
    def _url(self) -> str: ...

    @abstractmethod
    def _headers(self) -> dict[str, str]: ...

    @abstractmethod
    def _payload(self, request: ChatRequest) -> dict[str, Any]: ...

    @abstractmethod
    def _parse(self, data: dict[str, Any]) -> tuple[str, TokenUsage]: ...

    # -- the call ------------------------------------------------------------------------------
    def complete(self, request: ChatRequest) -> Completion:
        payload = deep_merge(self._payload(request), self._options)
        for path in self._dropped:
            _pop_path(payload, path)
        failures, delay = 0, 1.0
        while True:
            wait: float | None = None
            try:
                response = self._http.post(self._url(), json=payload, headers=self._headers())
            except httpx.HTTPError as err:
                failure = LLMError(f"{self.name}: network error: {err}", transient=True)
            else:
                if response.is_success:
                    return self._completion(response)
                if response.status_code in (400, 422) and self._drop_rejected_param(payload, response):
                    continue
                failure = self._failure(response)
                if not failure.transient:
                    raise failure
                wait = _retry_after(response)
            failures += 1
            if failures >= self._max_attempts:
                raise failure
            self._sleep(wait if wait is not None else delay)
            delay *= 2

    def _completion(self, response: httpx.Response) -> Completion:
        try:
            data = response.json()
        except ValueError:
            raise LLMError(f"{self.name}: the answer is not JSON: {response.text[:200]!r}") from None
        if not isinstance(data, dict):
            raise LLMError(f"{self.name}: unexpected answer: {str(data)[:200]}")
        text, usage = self._parse(data)
        return Completion(text=text, usage=usage, model=self.model)

    def _failure(self, response: httpx.Response) -> LLMError:
        status = response.status_code
        message = f"{self.name}: HTTP {status}: {error_message(response)}"
        if status in (401, 403) and self._auth_hint:
            message += f" {self._auth_hint}"
        return LLMError(message, transient=status in TRANSIENT_STATUSES, status=status)

    def _drop_rejected_param(self, payload: dict[str, Any], response: httpx.Response) -> bool:
        message = error_message(response).lower()
        for param in self.optional_params:
            if any(hint in message for hint in param.hints) and _pop_path(payload, param.path):
                self._dropped.add(param.path)
                return True
        return False
