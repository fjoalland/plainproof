"""Running a list of scenarios: one fresh browser each, reports written as they go and at the end."""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from plainproof.agent.runner import Agent
from plainproof.errors import ConfigError
from plainproof.llm.scripted import ScriptedClient
from plainproof.replay.storage import RecordingMissingError, recording_paths
from plainproof.results import RunResult, ScenarioOutcome
from plainproof.scenario import Scenario, load_scenarios
from plainproof.suite import run_suite
from tests.fakes import FakeBrowser

PASS = [{"step": 1, "action": "check", "text": "Welcome"}, {"step": 1, "action": "finish", "success": True}]
FAIL = [{"step": 1, "action": "finish", "success": False, "reason": "it broke"}]


def scenarios(tmp_path: Path, **files: str) -> list[Scenario]:
    folder = tmp_path / "e2e"
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / f"{name}.txt").write_text(text, encoding="utf-8")
    return load_scenarios(str(folder), env={})


def agents(scripts: dict[str, list[Any]]) -> Any:
    def make(scenario: Scenario) -> Agent:
        return Agent(ScriptedClient(scripts[scenario.name]), interpret=False, diagnose=False)

    return make


class Browsers:
    """A fresh fake browser per scenario, kept for inspection."""

    def __init__(self, cls: type[FakeBrowser] = FakeBrowser) -> None:
        self.cls = cls
        self.made: list[FakeBrowser] = []

    def __call__(self) -> FakeBrowser:
        browser = self.cls()
        self.made.append(browser)
        return browser


def test_every_scenario_runs_in_its_own_browser_and_gets_its_reports(tmp_path: Path) -> None:
    items = scenarios(tmp_path, **{"01-ok": "Verify Welcome", "02-ko": "Verify Goodbye"})
    browsers = Browsers()
    out = tmp_path / "report"
    suite = run_suite(items, out, agents({"01-ok": PASS, "02-ko": FAIL}), browsers, start_url="http://app/")
    assert [o.status for o in suite.outcomes] == ["passed", "failed"]
    assert len(browsers.made) == 2
    assert all(b.calls[0] == ("navigate", "http://app/") for b in browsers.made)
    assert browsers.made[0].video_path == out / "01-ok" / "video.webm"
    for name in ("01-ok", "02-ko"):
        assert {"report.json", "report.md", "report.html"} <= {p.name for p in (out / name).iterdir()}
    assert {"index.html", "summary.json", "junit.xml"} <= {p.name for p in out.iterdir()}
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert next(s["file"] for s in summary["scenarios"]).endswith("e2e/01-ok.txt")
    assert suite.started_at
    assert suite.finished_at
    assert not suite.ok


def test_a_passing_scenario_writes_its_recording_starting_at_the_given_url(tmp_path: Path) -> None:
    items = scenarios(tmp_path, **{"01-ok": "Verify Welcome", "02-ko": "Verify Goodbye"})
    messages: list[str] = []

    class Listener:
        def on_scenario_start(self, n: int, total: int, scenario: Scenario) -> None:
            messages.append(f"start {n}/{total} {scenario.name}")

        def on_scenario_end(self, outcome: ScenarioOutcome, run_dir: Path) -> None:
            messages.append(f"end {outcome.name} {outcome.status}")

        def on_recording(self, path: Path) -> None:
            messages.append(f"recorded {path.name}")

    run_suite(
        items,
        tmp_path / "report",
        agents({"01-ok": PASS, "02-ko": FAIL}),
        Browsers(),
        start_url="http://app/login",
        listener=Listener(),
    )
    ok_paths = recording_paths(items[0])
    ko_paths = recording_paths(items[1])
    assert ok_paths is not None
    assert ko_paths is not None
    recording = json.loads(ok_paths[0].read_text(encoding="utf-8"))
    assert recording["start_url"] == "http://app/login", "never a login redirect with one-time tokens"
    assert ok_paths[1].is_file()
    assert not ko_paths[0].exists(), "a failing run never overwrites a recording"
    assert messages == [
        "start 1/2 01-ok",
        "end 01-ok passed",
        "recorded 01-ok.json",
        "start 2/2 02-ko",
        "end 02-ko failed",
    ]


def test_recording_can_be_turned_off(tmp_path: Path) -> None:
    items = scenarios(tmp_path, **{"01-ok": "Verify Welcome"})
    run_suite(items, tmp_path / "report", agents({"01-ok": PASS}), Browsers(), record=False)
    paths = recording_paths(items[0])
    assert paths is not None
    assert not paths[0].exists()


def test_a_scenario_that_cannot_start_is_an_error_and_the_suite_goes_on(tmp_path: Path) -> None:
    items = scenarios(tmp_path, **{"01-missing": "x", "02-ok": "Verify Welcome"})

    def make(scenario: Scenario) -> Agent:
        if scenario.name == "01-missing":
            raise RecordingMissingError("No recording for this scenario")
        return Agent(ScriptedClient(PASS), interpret=False, diagnose=False)

    suite = run_suite(items, tmp_path / "report", make, Browsers())
    assert [o.status for o in suite.outcomes] == ["error", "passed"]
    assert suite.outcomes[0].reason == "No recording for this scenario"
    assert (tmp_path / "report" / "01-missing" / "report.html").is_file()


def test_a_browser_that_does_not_start(tmp_path: Path) -> None:
    class Broken(FakeBrowser):
        def __enter__(self) -> FakeBrowser:
            raise ConfigError("Cannot start chromium")

    items = scenarios(tmp_path, **{"01-ok": "Verify Welcome"})
    suite = run_suite(items, tmp_path / "report", agents({"01-ok": PASS}), Browsers(Broken))
    assert suite.outcomes[0].reason == "Cannot start chromium"


def test_an_unexpected_crash_names_its_type(tmp_path: Path) -> None:
    class Crashing(FakeBrowser):
        def navigate(self, url: str) -> str:
            raise RuntimeError("net::ERR_CONNECTION_REFUSED at http://app/")

    items = scenarios(tmp_path, **{"01-ok": "Verify Welcome"})
    suite = run_suite(items, tmp_path / "report", agents({"01-ok": PASS}), Browsers(Crashing), start_url="http://app/")
    assert suite.outcomes[0].reason == "RuntimeError: net::ERR_CONNECTION_REFUSED at http://app/"


def test_ctrl_c_stops_the_suite_but_keeps_the_reports(tmp_path: Path) -> None:
    class Interrupted(FakeBrowser):
        def __exit__(
            self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
        ) -> None:
            self.closed = True

    def make(scenario: Scenario) -> Any:
        class Runner:
            def run(self, scenario: Scenario, browser: Any, out_dir: Path) -> RunResult:
                raise KeyboardInterrupt

        return Runner()

    items = scenarios(tmp_path, **{"01-a": "x", "02-b": "y"})
    browsers = Browsers(Interrupted)
    suite = run_suite(items, tmp_path / "report", make, browsers)
    assert [o.name for o in suite.outcomes] == ["01-a"]
    assert "interrupted" in suite.outcomes[0].reason
    assert browsers.made[0].closed  # type: ignore[attr-defined]
    assert (tmp_path / "report" / "index.html").is_file()


def test_an_update_replaces_only_the_scenarios_run_again(tmp_path: Path) -> None:
    items = scenarios(tmp_path, **{"01-ok": "Verify Welcome", "02-ko": "Verify Goodbye"})
    out = tmp_path / "report"
    first = run_suite(items, out, agents({"01-ok": PASS, "02-ko": FAIL}), Browsers())
    (out / "02-ko" / "stale.png").write_bytes(b"old")
    second = run_suite(items[1:], out, agents({"02-ko": PASS}), Browsers(), update=True)
    assert [o.name for o in second.outcomes] == ["01-ok", "02-ko"]
    assert [o.status for o in second.outcomes] == ["passed", "passed"]
    assert second.started_at == first.started_at
    assert not (out / "02-ko" / "stale.png").exists()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] == 2


def test_a_canary_that_fails_keeps_the_suite_green(tmp_path: Path) -> None:
    items = scenarios(tmp_path, **{"01-canary": "# expect: failure\nVerify Goodbye"})
    suite = run_suite(items, tmp_path / "report", agents({"01-canary": FAIL}), Browsers())
    assert suite.outcomes[0].status == "expected-failure"
    assert suite.ok


@pytest.mark.parametrize("label", ["", "staging · v2"])
def test_the_label_reaches_the_reports(tmp_path: Path, label: str) -> None:
    items = scenarios(tmp_path, **{"01-ok": "Verify Welcome"})
    suite = run_suite(items, tmp_path / "report", agents({"01-ok": PASS}), Browsers(), label=label)
    assert suite.label == label
    if label:
        assert label in (tmp_path / "report" / "index.html").read_text(encoding="utf-8")


def test_an_update_from_a_single_file_keeps_the_name_it_has_in_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Run alone, e2e/orders/02-refund.txt is named "02-refund"; in the full suite it is "orders-02-refund".
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "e2e" / "orders"
    folder.mkdir(parents=True)
    (folder / "02-refund.txt").write_text("Verify Welcome", encoding="utf-8")
    out = tmp_path / "report"
    full = load_scenarios(str(tmp_path / "e2e"), env={})
    run_suite(full, out, agents({"orders-02-refund": FAIL}), Browsers())
    alone = load_scenarios(str(folder / "02-refund.txt"), env={})
    suite = run_suite(alone, out, agents({"orders-02-refund": PASS}), Browsers(), update=True)
    assert [o.name for o in suite.outcomes] == ["orders-02-refund"]
    assert suite.outcomes[0].status == "passed"
    assert not (out / "02-refund").exists()
