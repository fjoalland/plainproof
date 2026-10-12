"""What a run costs: tokens counted from the answers, priced per model."""

import pytest

from plainproof.i18n import use_language
from plainproof.llm.base import TokenUsage
from plainproof.llm.pricing import (
    Price,
    UsageMeter,
    UsageReport,
    format_cost,
    format_tokens,
    price_for,
    usage_line,
)


class TestPriceFor:
    def test_builtin_price_by_longest_prefix(self) -> None:
        assert price_for("anthropic:claude-sonnet-5-5", env={}) == Price(2.0, 10.0, cache_read=0.10, cache_write=2.5)
        assert price_for("mistral:mistral-medium-latest", env={}) == Price(1.5, 7.5)

    def test_local_models_are_free(self) -> None:
        assert price_for("ollama:qwen2.5vl:7b", env={}) == Price(0.0, 0.0)

    def test_unknown_model_has_no_price(self) -> None:
        assert price_for("openrouter:some/model", env={}) is None

    def test_configured_prices_override_the_table(self) -> None:
        mine = {"anthropic:claude-sonnet": Price(1.0, 2.0)}
        assert price_for("anthropic:claude-sonnet-5-5", overrides=mine, env={}) == Price(1.0, 2.0)

    def test_environment_prices_win_over_everything(self) -> None:
        env = {"PLAINPROOF_PRICE_INPUT": "0.5", "PLAINPROOF_PRICE_OUTPUT": "1.5"}
        assert price_for("anthropic:claude-sonnet-5-5", env=env) == Price(0.5, 1.5)

    def test_a_malformed_environment_price_is_ignored(self) -> None:
        env = {"PLAINPROOF_PRICE_INPUT": "cheap", "PLAINPROOF_PRICE_OUTPUT": "1.5"}
        assert price_for("mistral:mistral-small-latest", env=env) == Price(0.15, 0.6)


def test_cost_uses_the_cache_prices_and_falls_back_to_the_input_price() -> None:
    usage = TokenUsage(
        input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=2_000_000, cache_write_tokens=1_000_000
    )
    assert Price(2.0, 10.0, cache_read=0.1, cache_write=2.5).cost(usage) == pytest.approx(2 + 1 + 0.2 + 2.5)
    assert Price(2.0, 10.0).cost(usage) == pytest.approx(2 + 1 + 4 + 2)


class TestUsageMeter:
    def test_counts_calls_tokens_and_cost(self) -> None:
        meter = UsageMeter()
        meter.add(TokenUsage(1000, 100))
        meter.add(TokenUsage(500, 50, cache_read_tokens=1000))
        report = meter.report(Price(1.0, 10.0))
        assert report == UsageReport(
            calls=2,
            input_tokens=1500,
            output_tokens=150,
            cache_read_tokens=1000,
            cache_write_tokens=0,
            cost_usd=pytest.approx(0.004),
        )

    def test_unknown_price_gives_no_cost(self) -> None:
        meter = UsageMeter()
        meter.add(TokenUsage(10, 1))
        assert meter.report(None).cost_usd is None


class TestUsageReport:
    def test_round_trip(self) -> None:
        report = UsageReport(calls=3, input_tokens=10, output_tokens=2, cost_usd=0.01)
        assert UsageReport.from_dict(report.to_dict()) == report
        assert UsageReport.from_dict(None) is None

    def test_sum_keeps_an_unknown_cost_unknown(self) -> None:
        known = UsageReport(calls=1, input_tokens=10, output_tokens=1, cost_usd=0.5)
        unknown = UsageReport(calls=1, input_tokens=5, output_tokens=1, cost_usd=None)
        assert (known + known).cost_usd == 1.0
        assert (known + unknown).cost_usd is None
        assert UsageReport.total([known, None, known]).calls == 2
        assert UsageReport.total([]).cost_usd is None


class TestFormatting:
    def test_english(self) -> None:
        assert format_cost(0.01234) == "$0.0123"
        assert format_cost(12.5) == "$12.50"
        assert format_cost(None) == "?"
        assert format_tokens(1234567) == "1,234,567"

    def test_french(self) -> None:
        with use_language("fr"):
            assert format_cost(0.01234) == "0,0123 $"
            assert format_tokens(1234567) == "1 234 567"

    def test_usage_line(self) -> None:
        report = UsageReport(calls=4, input_tokens=12000, output_tokens=345, cache_read_tokens=1000, cost_usd=0.02)
        assert usage_line(report) == "$0.0200 (13,000 tokens in, 345 out, 4 model calls)"
        assert usage_line(None) == "?"
