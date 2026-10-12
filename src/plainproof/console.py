"""What the command line prints while a suite runs.

Every dynamic text (scenarios, page texts, model answers) is printed as plain ``Text``, never
interpreted as Rich markup: "Clicked [3]" must not be read as a style tag.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .i18n import t
from .llm.pricing import format_cost, format_tokens, usage_line
from .report.paths import display_path
from .results import PlanStep, ScenarioOutcome, Step, SuiteResult
from .scenario import Scenario

_STATUS_KEYS = {
    "passed": "log.passed",
    "failed": "log.failed",
    "error": "log.failed",
    "expected-failure": "log.expected_failure",
    "unexpected-pass": "log.unexpected_pass",
}


class ConsoleReporter:
    """Follows the suite and every run (implements both listener protocols)."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def line(self, text: str, style: str = "") -> None:
        self.console.print(Text(text, style=style))

    # -- a run -------------------------------------------------------------------------------------
    def on_plan(self, plan: list[PlanStep]) -> None:
        self.line(t("log.plan", n=len(plan)), "cyan")
        for n, step in enumerate(plan, 1):
            text = Text.assemble((f"  {n:02d} ", "dim"), step.text)
            if step.verify:
                text.append(" ✓", style="blue")
            self.console.print(text)

    def on_step(self, step: Step) -> None:
        params = {k: v for k, v in step.action.items() if k not in ("action", "thought")}
        text = Text.assemble((f"{step.index:02d} ", "bold"), (step.kind or "?", "magenta"))
        if params:
            text.append(" " + json.dumps(params, ensure_ascii=False), style="dim")
        if step.error:
            text.append(f"  ✗ {step.error}", style="red")
        elif step.failed_check:
            text.append(f"  ✗ {step.result}", style="yellow")
        else:
            text.append(f"  ✓ {step.result}", style="green")
        self.console.print(text)
        if step.thought:
            self.line(f"     {step.thought}", "dim italic")

    # -- the suite ---------------------------------------------------------------------------------
    def on_scenario_start(self, n: int, total: int, scenario: Scenario) -> None:
        self.console.rule(Text(t("log.header", n=n, total=total, name=scenario.name), style="bold"))
        self.console.print(Panel(Text(scenario.source), title=Text(scenario.name), border_style="cyan", expand=False))

    def on_scenario_end(self, outcome: ScenarioOutcome, run_dir: Path) -> None:
        style = "bold green" if outcome.conforms else "bold red"
        self.line(t(_STATUS_KEYS[outcome.status], name=outcome.name, seconds=f"{outcome.duration_s:.0f}"), style)
        if outcome.usage is not None:
            self.line("  " + t("log.cost", line=usage_line(outcome.usage)), "dim")
        if not outcome.passed:
            diagnosis = outcome.diagnosis
            if diagnosis is not None:  # the model's explanation first
                self.line("  " + t("log.explanation", text=diagnosis.summary))
                self.line("  " + t("log.cause", cause=t("cause." + diagnosis.cause)))
            self.line("  " + outcome.reason)
            facts = outcome.explanation(technical_only=True)
            if facts:
                self.line("  " + facts.replace("\n", "\n  "), "dim")
            if diagnosis is not None and diagnosis.details:
                self.line("  " + diagnosis.details.replace("\n", "\n  "), "dim")
            self.line("  " + t("log.report", path=display_path(run_dir / "report.html")))

    def on_recording(self, path: Path) -> None:
        self.line("  " + t("log.recorded", path=display_path(path)), "dim")

    def summary(self, suite: SuiteResult, out_dir: Path) -> None:
        lines = Text()
        for outcome in suite.outcomes:
            mark, style = ("✓", "green") if outcome.conforms else ("✗", "red")
            cost = format_cost(outcome.usage.cost_usd) if outcome.usage else "—"
            lines.append(f"{mark} ", style=style)
            lines.append(f"{outcome.name}  ({outcome.duration_s:.0f}s · {cost})\n")
        usage = suite.usage
        lines.append(
            t(
                "cost.total",
                cost=format_cost(usage.cost_usd) if usage.calls else "—",
                tokens_in=format_tokens(usage.total_input_tokens),
                tokens_out=format_tokens(usage.output_tokens),
            ),
            style="dim",
        )
        title = Text(t("cli.summary_title", passed=suite.passed, failed=suite.failed))
        self.console.print(Panel(lines, title=title, border_style="green" if suite.ok else "red"))
        index, junit = display_path(out_dir / "index.html"), display_path(out_dir / "junit.xml")
        self.line(t("cli.report", index=index, junit=junit))
