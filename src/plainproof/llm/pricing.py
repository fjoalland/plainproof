"""What a run costs: tokens counted from the model answers, priced per model.

Built-in prices are a convenience, in US dollars per million tokens, read on the providers'
pricing pages on :data:`PRICES_CHECKED`. Prices change: override them in ``plainproof.toml``
(``[pricing."provider:model-prefix"]``) or with ``PLAINPROOF_PRICE_INPUT`` and
``PLAINPROOF_PRICE_OUTPUT``. A model without a price still reports its tokens, with no cost
rather than a wrong one. Cache discounts are applied when the cache prices are known.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from ..i18n import get_language, t
from .base import TokenUsage

PRICES_CHECKED = "2026-10-12"


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens. Cache prices default to the input price."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None

    def cost(self, usage: TokenUsage) -> float:
        cache_read = self.input if self.cache_read is None else self.cache_read
        cache_write = self.input if self.cache_write is None else self.cache_write
        return (
            usage.input_tokens * self.input
            + usage.output_tokens * self.output
            + usage.cache_read_tokens * cache_read
            + usage.cache_write_tokens * cache_write
        ) / 1_000_000


# "provider:model-prefix" -> price. The longest matching prefix wins.
BUILTIN_PRICES: dict[str, Price] = {
    "anthropic:claude-fable-5-1": Price(10.0, 50.0, cache_read=0.25, cache_write=12.5),
    "anthropic:claude-opus-5-5": Price(4.0, 20.0, cache_read=0.20, cache_write=5.0),
    "anthropic:claude-sonnet-5-5": Price(2.0, 10.0, cache_read=0.10, cache_write=2.5),
    # Haiku 5.5: prompts up to 100,000 tokens (plainproof's prompts stay well below).
    "anthropic:claude-haiku-5-5": Price(0.10, 0.50, cache_read=0.01, cache_write=0.125),
    "openai:gpt-6-astra": Price(10.0, 50.0, cache_read=1.0),
    "openai:gpt-6.1-sol": Price(2.0, 10.0, cache_read=0.10),
    "openai:gpt-6-luna": Price(0.10, 0.50, cache_read=0.01),
    # Gemini 3.8 Flash: introductory price until 2026-12-31, then 1.50 / 7.50.
    "gemini:gemini-3.8-flash": Price(0.75, 3.75, cache_read=0.075),
    "gemini:gemini-3.5-flash-lite": Price(0.30, 2.50, cache_read=0.03),
    "gemini:gemini-3.1-pro": Price(2.0, 12.0, cache_read=0.20),  # prompts up to 200k tokens
    "mistral:mistral-medium": Price(1.5, 7.5),
    "mistral:mistral-small": Price(0.15, 0.6),
    "mistral:mistral-large": Price(0.5, 1.5),
    # Models running on your own machine.
    "ollama:": Price(0.0, 0.0),
    "lmstudio:": Price(0.0, 0.0),
    "scripted:": Price(0.0, 0.0),
}


def _env_price(env: Mapping[str, str]) -> Price | None:
    raw_in, raw_out = env.get("PLAINPROOF_PRICE_INPUT"), env.get("PLAINPROOF_PRICE_OUTPUT")
    if not (raw_in and raw_out):
        return None
    try:
        return Price(float(raw_in), float(raw_out))
    except ValueError:
        return None


def price_for(
    model_name: str, overrides: Mapping[str, Price] | None = None, env: Mapping[str, str] | None = None
) -> Price | None:
    """The price of ``provider:model``: environment, then configuration, then the built-in table."""
    from_env = _env_price(os.environ if env is None else env)
    if from_env is not None:
        return from_env
    name = model_name.lower()
    for table in (overrides or {}, BUILTIN_PRICES):
        matches = [prefix for prefix in table if name.startswith(prefix.lower())]
        if matches:
            return table[max(matches, key=len)]
    return None


@dataclass(frozen=True)
class UsageReport:
    """Model calls, tokens and cost of a run, as written in reports."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: UsageReport) -> UsageReport:
        cost = None if self.cost_usd is None or other.cost_usd is None else self.cost_usd + other.cost_usd
        return UsageReport(
            self.calls + other.calls,
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            cost,
        )

    @staticmethod
    def total(reports: Iterable[UsageReport | None]) -> UsageReport:
        """Sum of several runs; the cost is unknown as soon as one of them is."""
        present = [r for r in reports if r is not None]
        if not present:
            return UsageReport()
        result = present[0]
        for report in present[1:]:
            result = result + report
        return result

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.cost_usd is not None:
            data["cost_usd"] = round(self.cost_usd, 6)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> UsageReport | None:
        if not data:
            return None
        cost = data.get("cost_usd")
        return cls(
            calls=int(data.get("calls") or 0),
            input_tokens=int(data.get("input_tokens") or 0),
            output_tokens=int(data.get("output_tokens") or 0),
            cache_read_tokens=int(data.get("cache_read_tokens") or 0),
            cache_write_tokens=int(data.get("cache_write_tokens") or 0),
            cost_usd=None if cost is None else float(cost),
        )


@dataclass
class UsageMeter:
    """Accumulates the usage of every model call of one run."""

    calls: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)

    def add(self, usage: TokenUsage) -> None:
        self.calls += 1
        self.usage = self.usage + usage

    def report(self, price: Price | None) -> UsageReport:
        return UsageReport(
            calls=self.calls,
            input_tokens=self.usage.input_tokens,
            output_tokens=self.usage.output_tokens,
            cache_read_tokens=self.usage.cache_read_tokens,
            cache_write_tokens=self.usage.cache_write_tokens,
            cost_usd=None if price is None else price.cost(self.usage),
        )


def format_cost(usd: float | None) -> str:
    """``$0.0123`` in English, ``0,0123 $`` in French, ``?`` when the price is unknown."""
    if usd is None:
        return "?"
    text = f"{usd:.4f}" if usd < 1 else f"{usd:.2f}"
    return f"{text.replace('.', ',')} $" if get_language() == "fr" else f"${text}"


def format_tokens(count: int) -> str:
    """``1,234`` in English, ``1 234`` in French."""
    text = f"{count:,}"
    return text.replace(",", " ") if get_language() == "fr" else text


def usage_line(report: UsageReport | None) -> str:
    """One line for logs and reports: cost, tokens and number of model calls."""
    if report is None:
        return "?"
    return t(
        "cost.line",
        cost=format_cost(report.cost_usd),
        tokens_in=format_tokens(report.total_input_tokens),
        tokens_out=format_tokens(report.output_tokens),
        calls=report.calls,
    )
