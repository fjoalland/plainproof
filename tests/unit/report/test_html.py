"""The HTML pages: a step-by-step page per scenario and the suite overview.

Static pages, no build step, no external resources: they open from disk, a CI artifact or any
static host, offline included."""

import re
from pathlib import Path

import pytest

from plainproof.i18n import use_language
from plainproof.report.html import NavItem, write_index, write_run_page
from plainproof.results import ScenarioOutcome

from .builders import a_suite, failed_run


@pytest.fixture
def failed(tmp_path: Path) -> ScenarioOutcome:
    run_dir = tmp_path / "02-orders"
    run_dir.mkdir()
    for name in ("step_01.png", "step_01_action.png", "step_02.png", "step_02_action.png", "final.png"):
        (run_dir / name).write_bytes(b"png")
    return ScenarioOutcome(
        name="02-orders",
        source=failed_run().scenario,
        result=failed_run(),
        duration_s=60.0,
        description="Orders are listed after creation.",
    )


def page(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestRunPage:
    def test_verdict_explanation_and_plan(self, failed: ScenarioOutcome, tmp_path: Path) -> None:
        html = page(write_run_page(failed, tmp_path / "02-orders", label="staging"))
        assert "<title>02-orders · Failed · plainproof</title>" in html
        assert "Orders are listed after creation." in html
        assert "How plainproof understood the scenario" in html
        assert "added from the project context" in html
        assert "line 2" in html
        assert "The order is missing from the list." in html
        assert "application behaviour" in html
        assert "staging" in html
        assert "$0.0321" in html

    def test_untrusted_text_is_escaped(self, failed: ScenarioOutcome, tmp_path: Path) -> None:
        html = page(write_run_page(failed, tmp_path / "02-orders"))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "Open the &lt;orders&gt;" in html

    def test_screenshots_are_referenced_by_relative_name(self, failed: ScenarioOutcome, tmp_path: Path) -> None:
        html = page(write_run_page(failed, tmp_path / "02-orders"))
        assert 'src="step_01_action.png"' in html
        assert 'src="final.png"' in html
        assert str(tmp_path) not in html
        assert "video.webm" not in html, "no video section without a video"

    def test_the_video_is_shown_when_recorded(self, failed: ScenarioOutcome, tmp_path: Path) -> None:
        (tmp_path / "02-orders" / "video.webm").write_bytes(b"webm")
        assert '<video src="video.webm"' in page(write_run_page(failed, tmp_path / "02-orders"))

    def test_failed_steps_are_open_and_others_folded(self, failed: ScenarioOutcome, tmp_path: Path) -> None:
        html = page(write_run_page(failed, tmp_path / "02-orders"))
        steps = re.findall(r'<details class="step[^"]*"( open)?', html)
        assert steps == ["", " open", " open", " open"], "error, failed check and verdict are unfolded"

    def test_navigation_between_scenarios(self, failed: ScenarioOutcome, tmp_path: Path) -> None:
        nav = [
            NavItem("01-login", "../01-login/report.html", "passed", 20.0),
            NavItem("02-orders", "../02-orders/report.html", "failed", 60.0),
            NavItem("03-canary", "../03-canary/report.html", "expected-failure", 10.0),
        ]
        html = page(write_run_page(failed, tmp_path / "02-orders", nav=nav))
        assert 'href="../01-login/report.html"' in html
        assert 'href="../03-canary/report.html"' in html
        assert "Scenario 2 of 3" in html

    def test_french(self, failed: ScenarioOutcome, tmp_path: Path) -> None:
        with use_language("fr"):
            html = page(write_run_page(failed, tmp_path / "02-orders"))
        assert '<html lang="fr">' in html
        assert "Comment plainproof a compris le scénario" in html
        assert "comportement de l&#39;application" in html
        assert "0,0321 $" in html

    def test_a_crash_has_a_page_too(self, tmp_path: Path) -> None:
        crash = ScenarioOutcome(name="04-crash", source="I export.", error="Cannot start chromium")
        html = page(write_run_page(crash, tmp_path / "04-crash"))
        assert "Cannot start chromium" in html


class TestIndex:
    def test_overview(self, tmp_path: Path) -> None:
        html = page(write_index(a_suite(), tmp_path))
        assert "<title>Suite results · 2 failures · plainproof</title>" in html
        for name in ("01-login", "02-orders", "03-canary", "04-crash"):
            assert f'href="{name}/report.html"' in html
        assert "Failed as expected" in html
        assert "staging · v2.3" in html
        assert 'href="junit.xml"' in html
        assert 'href="summary.json"' in html
        assert "&lt;script&gt;" in html
        assert "<script>alert(1)</script>" not in html

    def test_every_scenario_page_is_rewritten_with_the_navigation(self, tmp_path: Path) -> None:
        write_index(a_suite(), tmp_path)
        assert "Scenario 2 of 4" in page(tmp_path / "02-orders" / "report.html")

    def test_all_passed(self, tmp_path: Path) -> None:
        suite = a_suite()
        suite.outcomes = suite.outcomes[:1]
        assert "Suite passed" in page(write_index(suite, tmp_path))
