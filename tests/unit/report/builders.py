"""Runs and suites for the report tests."""

from __future__ import annotations

from plainproof.llm.pricing import UsageReport
from plainproof.results import Diagnosis, PlanStep, RunResult, ScenarioOutcome, Step, SuiteResult


def failed_run() -> RunResult:
    return RunResult(
        scenario="I open the orders.\nI see <b>Order 2050-001</b> <script>alert(1)</script>",
        model="anthropic:claude-sonnet-5-5",
        success=False,
        reason='Success verdict refused: the last check FAILED ("Order 2050-001").',
        steps=[
            Step(
                index=1,
                url="http://app/",
                action={"action": "click", "ref": 3, "label": "Orders", "thought": "go"},
                thought="Open the <orders>",
                result='Clicked [3] "Orders"',
                step_no=1,
                url_after="http://app/orders",
                screenshot="step_01.png",
                action_screenshot="step_01_action.png",
                duration_ms=1500,
            ),
            Step(
                index=2,
                url="http://app/orders",
                action={"action": "check", "text": "Order 2050-001"},
                result='CHECK FAILED: "Order 2050-001" not found in page',
                check=False,
                proof=True,
                step_no=2,
                screenshot="step_02.png",
                action_screenshot="step_02_action.png",
                duration_ms=500,
            ),
            Step(
                index=3,
                url="http://app/orders",
                action={"action": "click", "ref": 9},
                error="[9] does not exist",
                step_no=2,
                duration_ms=300,
            ),
            Step(
                index=4,
                url="http://app/orders",
                action={"action": "finish", "success": True},
                result="Verdict overridden",
                step_no=2,
            ),
        ],
        plan=[
            PlanStep("Log in", source=0),
            PlanStep("Click Orders", source=1),
            PlanStep('The order "Order 2050-001" is listed', verify=True, source=2),
        ],
        diagnosis=Diagnosis(
            summary="The order is missing from the list.", cause="application", details="Action 2 failed."
        ),
        usage=UsageReport(calls=5, input_tokens=12000, output_tokens=400, cost_usd=0.0321),
        started_at="2026-10-12T10:00:00",
        finished_at="2026-10-12T10:01:00",
    )


def passed_run() -> RunResult:
    return RunResult(
        scenario="I log in.",
        model="anthropic:claude-sonnet-5-5",
        success=True,
        reason="All checks passed",
        steps=[
            Step(
                index=1,
                url="http://app/",
                action={"action": "check", "text": "Welcome"},
                result='CHECK OK: "Welcome" found',
                check=True,
                step_no=1,
                duration_ms=800,
            ),
            Step(
                index=2,
                url="http://app/",
                action={"action": "finish", "success": True},
                result="Test finished",
                step_no=1,
            ),
        ],
        usage=UsageReport(calls=2, input_tokens=5000, output_tokens=100, cost_usd=0.01),
        started_at="2026-10-12T10:01:00",
        finished_at="2026-10-12T10:01:20",
    )


def a_suite() -> SuiteResult:
    return SuiteResult(
        outcomes=[
            ScenarioOutcome(
                name="01-login",
                source="I log in.",
                file="e2e/01-login.txt",
                result=passed_run(),
                duration_s=20.0,
                description="A valid account logs in.",
            ),
            ScenarioOutcome(
                name="02-orders",
                source=failed_run().scenario,
                file="e2e/02-orders.txt",
                result=failed_run(),
                duration_s=60.0,
            ),
            ScenarioOutcome(
                name="03-canary",
                source="I pay twice.",
                file="e2e/03-canary.txt",
                result=failed_run(),
                duration_s=10.0,
                expected_failure=True,
            ),
            ScenarioOutcome(
                name="04-crash",
                source="I export.",
                file="e2e/04-crash.txt",
                error="Cannot start chromium",
                duration_s=1.0,
            ),
        ],
        started_at="2026-10-12T10:00:00",
        finished_at="2026-10-12T10:02:00",
        label="staging · v2.3",
    )
