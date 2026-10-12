"""Provider-neutral types: what plainproof asks a model, and what it gets back.

plainproof only needs one thing from a model: given a system prompt and a user message
(text, optionally a screenshot), return a text answer (a JSON object) and the tokens it
cost. Every provider adapter implements :class:`LLMClient` on top of these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    media_type: str = "image/png"


Part = TextPart | ImagePart


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    parts: tuple[Part, ...]


@dataclass(frozen=True)
class ChatRequest:
    system: str
    messages: tuple[Message, ...]
    json_answer: bool = True
    """Ask for a JSON object when the provider supports it (the answer is parsed leniently anyway)."""
    max_output_tokens: int = 4096

    @classmethod
    def single(cls, system: str, text: str, image: bytes | None = None) -> ChatRequest:
        """One user message: the screenshot first (vision models read it best that way), then the text."""
        parts: tuple[Part, ...] = (ImagePart(image), TextPart(text)) if image else (TextPart(text),)
        return cls(system=system, messages=(Message(role="user", parts=parts),))

    @property
    def has_images(self) -> bool:
        return any(isinstance(p, ImagePart) for m in self.messages for p in m.parts)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    """Input tokens billed at the full price (cache reads and writes excluded)."""
    output_tokens: int = 0
    """Output tokens, reasoning included."""
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


@dataclass(frozen=True)
class Completion:
    text: str
    usage: TokenUsage
    model: str = ""


class LLMError(Exception):
    """A model call that failed. ``transient`` errors (rate limit, overload, network) may be retried."""

    def __init__(self, message: str, *, transient: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.status = status


@runtime_checkable
class LLMClient(Protocol):
    """What plainproof needs from a model. Implement it to plug any provider (see docs/llm-providers.md)."""

    @property
    def name(self) -> str:
        """``provider:model``, as shown in reports and used to look up prices."""
        ...

    @property
    def vision(self) -> bool:
        """Whether screenshots are sent along with the element list."""
        ...

    def complete(self, request: ChatRequest) -> Completion:
        """Answer one request. Raise :class:`LLMError` on failure."""
        ...
