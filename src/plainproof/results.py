"""The outcome of a scenario run: every action with its evidence, the verdict and its cost.

These objects are written to ``report.json`` (screenshots are referenced by file name, next
to it) and read back to rebuild reports, so they never hold absolute paths or secrets.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any, Protocol

from .i18n import t
from .llm.pricing import UsageReport

CAUSES = ("scenario", "application", "agent", "environment", "unknown")


@dataclass
class PlanStep:
    """One precise step of a scenario, as the model understood it before running it."""

    text: str
    verify: bool = False
    absent: bool = False
    """For a verification: something that must NOT be shown (any more)."""
    source: int = 0
    """The scenario line it comes from (1-based); 0 for a step added from the project context."""

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "verify": self.verify, "absent": self.absent, "source": self.source}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PlanStep:
        return cls(
            text=str(data.get("text", "")),
            verify=bool(data.get("verify")),
            absent=bool(data.get("absent")),
            source=int(data.get("source") or 0),
        )


@dataclass(frozen=True)
class Diagnosis:
    """The model's plain-language explanation of a failure."""

    summary: str
    cause: str = "unknown"
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary, "cause": self.cause, "details": self.details}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> Diagnosis | None:
        if not data or not str(data.get("summary") or "").strip():
            return None
        cause = str(data.get("cause") or "unknown").strip().lower()
        return cls(
            summary=str(data["summary"]).strip(),
            cause=cause if cause in CAUSES else "unknown",
            details=str(data.get("details") or "").strip(),
        )


@dataclass
class Step:
    """One action of a run: what the model decided, and what happened."""

    index: int
    url: str
    action: dict[str, Any]
    thought: str = ""
    result: str = ""
    error: str | None = None
    check: bool | None = None
    """None for an action; True or False for a verification and its outcome."""
    proof: bool | None = None
    """For a verification step of the plan: does this check prove it?"""
    step_no: int = 0
    """The scenario step the action belongs to."""
    url_after: str = ""
    screenshot: str = ""
    """File name of the annotated screenshot the model saw."""
    action_screenshot: str = ""
    """File name of the screenshot with the targeted element highlighted."""
    duration_ms: int = 0

    @property
    def kind(self) -> str:
        return str(self.action.get("action", ""))

    @property
    def failed_check(self) -> bool:
        return self.check is False

    @property
    def outcome(self) -> str:
        return f"ERROR: {self.error}" if self.error else self.result

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Step:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class RunResult:
    scenario: str
    """The scenario as its author wrote it."""
    model: str
    success: bool | None = None
    reason: str = ""
    steps: list[Step] = field(default_factory=list)
    plan: list[PlanStep] | None = None
    diagnosis: Diagnosis | None = None
    usage: UsageReport | None = None
    started_at: str = ""
    finished_at: str = ""
    recording: dict[str, Any] | None = None
    """Replayable actions of a passing run; written next to the scenario, not in report.json."""

    @property
    def duration_ms(self) -> int:
        return sum(step.duration_ms for step in self.steps)

    @property
    def action_errors(self) -> int:
        return sum(1 for step in self.steps if step.error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "model": self.model,
            "success": self.success,
            "reason": self.reason,
            "plan": [p.to_dict() for p in self.plan] if self.plan is not None else None,
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "usage": self.usage.to_dict() if self.usage else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunResult:
        plan = data.get("plan")
        return cls(
            scenario=str(data.get("scenario", "")),
            model=str(data.get("model", "")),
            success=data.get("success"),
            reason=str(data.get("reason", "")),
            steps=[Step.from_dict(s) for s in data.get("steps") or []],
            plan=[PlanStep.from_dict(p) for p in plan] if plan is not None else None,
            diagnosis=Diagnosis.from_dict(data.get("diagnosis")),
            usage=UsageReport.from_dict(data.get("usage")),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
        )


@dataclass
class ScenarioOutcome:
    """One scenario of a suite: what was run, and how it ended."""

    name: str
    source: str
    """The scenario as its author wrote it."""
    description: str = ""
    file: str = ""
    """Where the scenario comes from, as shown in reports (never an absolute path)."""
    expected_failure: bool = False
    result: RunResult | None = None
    duration_s: float = 0.0
    error: str | None = None
    """A crash outside the run itself (the browser could not start, a recording is missing...)."""

    @property
    def passed(self) -> bool:
        return self.result is not None and self.result.success is True

    @property
    def status(self) -> str:
        """passed, failed, expected-failure (a canary that caught its defect), unexpected-pass, or error."""
        if self.error or self.result is None:
            return "error"
        if self.expected_failure:
            return "unexpected-pass" if self.passed else "expected-failure"
        return "passed" if self.passed else "failed"

    @property
    def conforms(self) -> bool:
        return self.status in ("passed", "expected-failure")

    @property
    def reason(self) -> str:
        if self.error:
            return self.error
        return self.result.reason if self.result else t("expl.no_result")

    @property
    def usage(self) -> UsageReport | None:
        return self.result.usage if self.result else None

    @property
    def diagnosis(self) -> Diagnosis | None:
        return self.result.diagnosis if self.result else None

    def explanation(self, technical_only: bool = False) -> str:
        """Why it failed: the model's summary and the reason, then the facts (failed checks,
        errors, last page). ``technical_only`` leaves out the summary and the reason."""
        if self.passed:
            return ""
        lines: list[str] = []
        if not technical_only:
            if self.diagnosis:
                lines.append(self.diagnosis.summary)
            lines.append(self.reason)
        if self.result is not None:
            steps = self.result.steps
            lines += [
                t("expl.step_check", n=s.index, result=s.result) for s in [s for s in steps if s.failed_check][-2:]
            ]
            lines += [
                t("expl.step_error", n=s.index, action=s.kind, error=s.error)
                for s in [s for s in steps if s.error][-2:]
            ]
            if steps:
                lines.append(t("expl.last_page", url=steps[-1].url_after or steps[-1].url))
        return "\n".join(lines)


@dataclass
class SuiteResult:
    outcomes: list[ScenarioOutcome] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    label: str = ""
    """What was tested (environment, version, branch), shown in the reports' header."""

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        """Scenarios that conform (passed, or failed as expected)."""
        return sum(1 for o in self.outcomes if o.conforms)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def ok(self) -> bool:
        return self.failed == 0

    @property
    def duration_s(self) -> float:
        return sum(o.duration_s for o in self.outcomes)

    @property
    def usage(self) -> UsageReport:
        return UsageReport.total(o.usage for o in self.outcomes)

    @property
    def model(self) -> str:
        return next((o.result.model for o in self.outcomes if o.result), "")


class RunListener(Protocol):
    """Follows a run as it happens (the command line prints it)."""

    def on_plan(self, plan: list[PlanStep]) -> None: ...

    def on_step(self, step: Step) -> None: ...


class SilentListener:
    def on_plan(self, plan: list[PlanStep]) -> None:
        pass

    def on_step(self, step: Step) -> None:
        pass
