"""Machine-readable outputs: report.json, report.md, summary.json, junit.xml.

Reports get published (CI artifacts, static pages): they must never reveal the machine that
produced them. A first publication of the original tool showed the full temporary path of the
run, user name included."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from plainproof.report.files import write_run_files
from plainproof.report.junit import write_junit
from plainproof.report.paths import display_path
from plainproof.report.summary import load_previous, write_summary

from .builders import a_suite, failed_run


class TestDisplayPath:
    def test_relative_paths_stay_as_they_are(self) -> None:
        assert display_path("e2e/scenarios") == "e2e/scenarios"
        assert display_path(None) == ""

    def test_inside_the_working_directory(self) -> None:
        assert display_path(Path.cwd() / "e2e" / "01.txt") == "e2e/01.txt"

    def test_outside_only_the_last_two_parts(self, tmp_path: Path) -> None:
        assert display_path(tmp_path / "secret-user" / "scenarios" / "01-login.txt") == "scenarios/01-login.txt"


def test_run_files(tmp_path: Path) -> None:
    write_run_files(failed_run(), tmp_path, name="02-orders")
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["steps"][0]["screenshot"] == "step_01.png"
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert markdown.startswith("# 02-orders: FAILED")
    assert "**What went wrong:** The order is missing from the list." in markdown
    assert "**Probable cause:** application behaviour" in markdown
    assert "### Action 2: `check`" in markdown
    assert "![action 2](step_02_action.png)" in markdown
    assert "- Result: ERROR: [9] does not exist" in markdown


class TestSummary:
    def test_summary_json(self, tmp_path: Path) -> None:
        write_summary(a_suite(), tmp_path)
        data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
        assert data["tool"] == "plainproof"
        assert (data["passed"], data["failed"], data["total"]) == (2, 2, 4)
        assert data["label"] == "staging · v2.3"
        assert data["usage"]["calls"] == 12
        first, second, canary, crash = data["scenarios"]
        assert first == {
            "name": "01-login",
            "file": "e2e/01-login.txt",
            "description": "A valid account logs in.",
            "scenario": "I log in.",
            "status": "passed",
            "conforms": True,
            "expected_failure": False,
            "reason": "All checks passed",
            "explanation": "",
            "diagnosis": None,
            "duration_s": 20.0,
            "actions": 2,
            "usage": first["usage"],
            "report": "01-login/report.html",
        }
        assert second["status"] == "failed"
        assert second["diagnosis"]["cause"] == "application"
        assert canary["status"] == "expected-failure"
        assert canary["conforms"] is True
        assert crash["status"] == "error"
        assert crash["reason"] == "Cannot start chromium"

    def test_an_update_keeps_the_scenarios_it_does_not_rerun(self, tmp_path: Path) -> None:
        suite = a_suite()
        for outcome in suite.outcomes:
            if outcome.result is not None:
                write_run_files(outcome.result, tmp_path / outcome.name, name=outcome.name)
        write_summary(suite, tmp_path)
        started, kept = load_previous(tmp_path, exclude={"02-orders"})
        assert started == "2026-10-12T10:00:00"
        assert [o.name for o in kept] == ["01-login", "03-canary"]
        login, canary = kept
        assert login.file == "e2e/01-login.txt"
        assert login.duration_s == 20.0
        assert login.description == "A valid account logs in."
        assert login.result is not None
        assert login.result.success is True
        assert canary.expected_failure is True
        assert canary.status == "expected-failure"

    def test_an_update_without_summary_still_finds_the_reports(self, tmp_path: Path) -> None:
        write_run_files(failed_run(), tmp_path / "02-orders", name="02-orders")
        (tmp_path / "broken").mkdir()
        (tmp_path / "broken" / "report.json").write_text("{nope", encoding="utf-8")
        started, kept = load_previous(tmp_path, exclude=set())
        assert started == ""
        assert [o.name for o in kept] == ["02-orders"]
        assert kept[0].source == failed_run().scenario


class TestJunit:
    @pytest.fixture
    def root(self, tmp_path: Path) -> ET.Element:
        write_junit(a_suite(), tmp_path / "junit.xml")
        return ET.parse(tmp_path / "junit.xml").getroot()

    def test_counts(self, root: ET.Element) -> None:
        assert root.tag == "testsuite"
        assert root.attrib["name"] == "plainproof"
        assert (root.attrib["tests"], root.attrib["failures"], root.attrib["errors"]) == ("4", "1", "1")
        assert root.attrib["time"] == "91.0"

    def test_a_passing_scenario_and_an_expected_failure_are_successes(self, root: ET.Element) -> None:
        cases = {c.attrib["name"]: c for c in root}
        assert cases["01-login"].find("failure") is None
        assert cases["03-canary"].find("failure") is None
        assert "failed as expected" in (cases["03-canary"].findtext("system-out") or "").lower()

    def test_a_failure_shows_the_explanation_first(self, root: ET.Element) -> None:
        failure = {c.attrib["name"]: c for c in root}["02-orders"].find("failure")
        assert failure is not None
        assert failure.attrib["message"] == "The order is missing from the list."
        assert "Technical details:\nAction 2 failed." in (failure.text or "")
        assert "Actions:\n1. click" in (failure.text or "")
        assert "$0.0321" in ({c.attrib["name"]: c for c in root}["02-orders"].findtext("system-out") or "")

    def test_a_crash_is_an_error(self, root: ET.Element) -> None:
        error = {c.attrib["name"]: c for c in root}["04-crash"].find("error")
        assert error is not None
        assert error.attrib["message"] == "Cannot start chromium"
