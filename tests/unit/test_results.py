"""The outcome of a run, as written to report.json and read back for reports and updates."""

from plainproof.llm.pricing import UsageReport
from plainproof.results import Diagnosis, PlanStep, RunResult, ScenarioOutcome, Step, SuiteResult


def a_run() -> RunResult:
    return RunResult(
        scenario="I open the app.\nI see the dashboard.",
        model="anthropic:claude-sonnet-5-5",
        success=False,
        reason="Success verdict refused",
        steps=[
            Step(
                index=1,
                url="http://app/",
                action={"action": "click", "ref": 3, "label": "Login"},
                thought="log in",
                result='Clicked [3] "Login"',
                step_no=1,
                url_after="http://app/home",
                screenshot="step_01.png",
                action_screenshot="step_01_action.png",
                duration_ms=1200,
            ),
            Step(
                index=2,
                url="http://app/home",
                action={"action": "check", "text": "Dashboard"},
                result='CHECK FAILED: "Dashboard" not found in page',
                check=False,
                proof=True,
                step_no=2,
            ),
            Step(index=3, url="http://app/home", action={"action": "click", "ref": 9}, error="[9] does not exist"),
        ],
        plan=[PlanStep("Log in", source=0), PlanStep("The dashboard is shown", verify=True, source=2)],
        diagnosis=Diagnosis(summary="The dashboard never showed up.", cause="application", details="step 2"),
        usage=UsageReport(calls=4, input_tokens=9000, output_tokens=300, cost_usd=0.02),
        started_at="2026-10-12T10:00:00",
        finished_at="2026-10-12T10:01:00",
        recording={"steps": []},
    )


def test_round_trip_through_a_dict() -> None:
    run = a_run()
    data = run.to_dict()
    assert "recording" not in data, "a recording is written next to the scenario, not in the report"
    back = RunResult.from_dict(data)
    run.recording = None
    assert back == run


def test_reading_a_minimal_or_older_report() -> None:
    run = RunResult.from_dict({"scenario": "x", "model": "m", "steps": [{"index": 1, "url": "u", "action": {}}]})
    assert run.success is None
    assert run.plan is None
    assert run.diagnosis is None
    assert run.usage is None
    assert run.steps[0].kind == ""
    assert run.steps[0].check is None


def test_step_helpers() -> None:
    steps = a_run().steps
    assert steps[0].kind == "click"
    assert steps[0].outcome == 'Clicked [3] "Login"'
    assert steps[1].failed_check
    assert not steps[0].failed_check
    assert steps[2].outcome == "ERROR: [9] does not exist"


def test_run_totals() -> None:
    run = a_run()
    assert run.duration_ms == 1200
    assert run.action_errors == 1


def test_diagnosis_cause_is_normalised() -> None:
    assert Diagnosis.from_dict({"summary": "s", "cause": " Application "}).cause == "application"
    assert Diagnosis.from_dict({"summary": "s", "cause": "aliens"}).cause == "unknown"
    assert Diagnosis.from_dict({"summary": " "}) is None
    assert Diagnosis.from_dict(None) is None


# -- scenarios within a suite -------------------------------------------------------------------
def outcome(success: bool | None, *, expected_failure: bool = False, error: str | None = None) -> ScenarioOutcome:
    result = None if error else RunResult(scenario="x", model="m", success=success, reason=f"reason {success}")
    return ScenarioOutcome(name="s", source="x", expected_failure=expected_failure, result=result, error=error)


def test_status_and_conformity() -> None:
    assert outcome(True).status == "passed"
    assert outcome(True).conforms
    assert outcome(False).status == "failed"
    assert not outcome(False).conforms
    # a canary scenario checks that a known defect is caught: it conforms when it fails
    assert outcome(False, expected_failure=True).status == "expected-failure"
    assert outcome(False, expected_failure=True).conforms
    assert outcome(True, expected_failure=True).status == "unexpected-pass"
    assert not outcome(True, expected_failure=True).conforms
    # a crash is never the expected failure
    assert outcome(None, expected_failure=True, error="browser failed").status == "error"
    assert not outcome(None, expected_failure=True, error="browser failed").conforms


def test_reason_prefers_the_crash() -> None:
    assert outcome(False).reason == "reason False"
    assert outcome(None, error="boom").reason == "boom"
    assert ScenarioOutcome(name="s", source="x").reason == "no result"


def test_explanation_of_a_failure() -> None:
    result = a_run()
    failed = ScenarioOutcome(name="s", source="x", result=result)
    text = failed.explanation()
    assert text.startswith("The dashboard never showed up.\nSuccess verdict refused")
    assert 'action 2: CHECK FAILED: "Dashboard" not found in page' in text
    assert "action 3: click -> ERROR [9] does not exist" in text
    assert text.endswith("last page: http://app/home")
    assert not failed.explanation(technical_only=True).startswith("The dashboard")
    result.success = True
    assert failed.explanation() == ""


def test_suite_totals() -> None:
    suite = SuiteResult(outcomes=[outcome(True), outcome(False), outcome(False, expected_failure=True)])
    assert (suite.total, suite.passed, suite.failed) == (3, 2, 1)
    assert not suite.ok
    assert SuiteResult(outcomes=[outcome(True)]).ok
    priced = SuiteResult(outcomes=[ScenarioOutcome(name="a", source="x", result=a_run())] * 2)
    assert priced.usage.calls == 8
    assert priced.usage.cost_usd == 0.04
    assert priced.model == "anthropic:claude-sonnet-5-5"
