"""Running a list of scenarios, one after another, each in a fresh browser.

Each scenario's report is written as soon as it finishes (an interrupted suite keeps what
already ran); the overview, summary.json and junit.xml are written at the end. A scenario
that passes with a model leaves a recording next to its file, replayable without a model.
"""

from __future__ import annotations

import dataclasses
import shutil
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .browser.driver import BrowserDriver
from .errors import PlainproofError
from .i18n import t
from .replay.storage import write_recording
from .report.files import write_run_files
from .report.html import write_index, write_run_page
from .report.junit import write_junit
from .report.paths import display_path
from .report.summary import load_previous, names_by_file, write_summary
from .results import RunResult, ScenarioOutcome, SuiteResult
from .scenario import Scenario


class Runner(Protocol):
    """Runs one scenario: the agent (with a model) or the replayer (without)."""

    def run(self, scenario: Scenario, browser: BrowserDriver, out_dir: Path) -> RunResult: ...


class SuiteListener(Protocol):
    def on_scenario_start(self, n: int, total: int, scenario: Scenario) -> None: ...

    def on_scenario_end(self, outcome: ScenarioOutcome, run_dir: Path) -> None: ...

    def on_recording(self, path: Path) -> None: ...


class _Quiet:
    def on_scenario_start(self, n: int, total: int, scenario: Scenario) -> None:
        pass

    def on_scenario_end(self, outcome: ScenarioOutcome, run_dir: Path) -> None:
        pass

    def on_recording(self, path: Path) -> None:
        pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _describe(error: Exception) -> str:
    if isinstance(error, PlainproofError):
        return str(error)  # written for the user already
    text = str(error).strip()
    return f"{type(error).__name__}: {text.splitlines()[0]}" if text else type(error).__name__


def run_suite(
    scenarios: Sequence[Scenario],
    out_dir: Path,
    make_runner: Callable[[Scenario], Runner],
    make_browser: Callable[[], BrowserDriver],
    *,
    start_url: str | None = None,
    update: bool = False,
    record: bool = True,
    label: str = "",
    listener: SuiteListener | None = None,
) -> SuiteResult:
    """Run ``scenarios`` and write the reports to ``out_dir``.

    With ``update``, ``out_dir`` is an existing report: only the given scenarios are replaced,
    the others are kept, and the overview, summary.json and junit.xml cover them all.
    """
    events: SuiteListener = listener or _Quiet()
    suite = SuiteResult(started_at=_now(), label=label)
    out_dir.mkdir(parents=True, exist_ok=True)
    if update:
        names = names_by_file(out_dir)
        scenarios = [
            dataclasses.replace(s, name=names.get(display_path(s.path), s.name)) if s.path else s for s in scenarios
        ]
    for n, scenario in enumerate(scenarios, 1):
        events.on_scenario_start(n, len(scenarios), scenario)
        run_dir = out_dir / scenario.name
        if update and run_dir.is_dir():
            shutil.rmtree(run_dir)  # no screenshot of the previous run left behind
        started = time.monotonic()
        result: RunResult | None = None
        error: str | None = None
        interrupted = False
        try:
            runner = make_runner(scenario)
            browser = make_browser()
            browser.video_path = run_dir / "video.webm"
            with browser:
                if start_url:
                    browser.navigate(start_url)
                result = runner.run(scenario, browser, run_dir)
        except KeyboardInterrupt:  # Ctrl-C: stop, but keep the reports of what already ran
            interrupted, error = True, t("expl.interrupted")
        except Exception as err:  # noqa: BLE001 - one broken scenario must not stop the suite
            error = _describe(err)
        outcome = ScenarioOutcome(
            name=scenario.name,
            source=scenario.source,
            description=scenario.description,
            file=display_path(scenario.path),
            expected_failure=scenario.expected_failure,
            result=result,
            duration_s=time.monotonic() - started,
            error=error,
        )
        suite.outcomes.append(outcome)
        if result is not None:
            write_run_files(result, run_dir, scenario.name)
        write_run_page(outcome, run_dir, label=label)
        events.on_scenario_end(outcome, run_dir)
        if record and result is not None and outcome.passed and result.recording:
            if start_url:  # the first page seen may be a login redirect carrying one-time tokens
                result.recording["start_url"] = start_url
            written = write_recording(result.recording, scenario)
            if written is not None:
                events.on_recording(written)
        if interrupted:
            break
    suite.finished_at = _now()
    if update:
        previous_start, kept = load_previous(out_dir, exclude={o.name for o in suite.outcomes})
        suite.started_at = previous_start or suite.started_at
        suite.outcomes = sorted([*kept, *suite.outcomes], key=lambda o: o.name)
    write_summary(suite, out_dir)
    write_junit(suite, out_dir / "junit.xml")
    write_index(suite, out_dir)
    return suite
