"""summary.json: the whole suite for programs, and the memory of a report updated in place."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import __version__
from ..results import RunResult, ScenarioOutcome, SuiteResult

SUMMARY_FILE = "summary.json"


def outcome_to_dict(outcome: ScenarioOutcome) -> dict[str, Any]:
    result = outcome.result
    return {
        "name": outcome.name,
        "file": outcome.file,
        "description": outcome.description,
        "scenario": outcome.source,
        "status": outcome.status,
        "conforms": outcome.conforms,
        "expected_failure": outcome.expected_failure,
        "reason": outcome.reason,
        "explanation": outcome.explanation(),
        "diagnosis": outcome.diagnosis.to_dict() if outcome.diagnosis else None,
        "duration_s": round(outcome.duration_s, 1),
        "actions": len(result.steps) if result else 0,
        "usage": outcome.usage.to_dict() if outcome.usage else None,
        "report": f"{outcome.name}/report.html",
    }


def write_summary(suite: SuiteResult, out_dir: Path) -> None:
    data = {
        "tool": "plainproof",
        "version": __version__,
        "label": suite.label,
        "started_at": suite.started_at,
        "finished_at": suite.finished_at,
        "model": suite.model,
        "total": suite.total,
        "passed": suite.passed,
        "failed": suite.failed,
        "usage": suite.usage.to_dict(),
        "scenarios": [outcome_to_dict(o) for o in suite.outcomes],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / SUMMARY_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_previous(out_dir: Path, exclude: set[str]) -> tuple[str, list[ScenarioOutcome]]:
    """(start of the previous run, scenarios of an existing report that are not run again).

    Each scenario is rebuilt from its report.json; summary.json, when present, gives back what
    only it knows (scenario file, description, duration, expected failure)."""
    summary = _read(out_dir / SUMMARY_FILE)
    previous = {s.get("name"): s for s in summary.get("scenarios", []) if isinstance(s, dict)}
    outcomes = []
    for report in sorted(out_dir.glob("*/report.json")):
        name = report.parent.name
        data = _read(report)
        if name in exclude or not data:
            continue
        result = RunResult.from_dict(data)
        meta = previous.get(name, {})
        outcomes.append(
            ScenarioOutcome(
                name=name,
                source=str(meta.get("scenario") or result.scenario),
                description=str(meta.get("description") or ""),
                file=str(meta.get("file") or ""),
                expected_failure=bool(meta.get("expected_failure")),
                result=result,
                duration_s=float(meta.get("duration_s") or 0),
            )
        )
    return str(summary.get("started_at") or ""), outcomes


def names_by_file(out_dir: Path) -> dict[str, str]:
    """{scenario file: scenario name} of an existing report. A scenario run on its own is named
    after its file ("02-refund"), within its suite after its path ("orders-02-refund"): an update
    gives it back the name it has in the report."""
    scenarios = _read(out_dir / SUMMARY_FILE).get("scenarios", [])
    return {
        str(s["file"]): str(s["name"]) for s in scenarios if isinstance(s, dict) and s.get("file") and s.get("name")
    }
