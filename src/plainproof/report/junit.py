"""junit.xml: one test case per scenario, for the test tabs of CI systems (GitHub, GitLab, Jenkins).

A failure's message is what CI shows first: the model's plain-language explanation when there
is one. A canary scenario that failed as expected is a success; a crash is an error.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ..i18n import t
from ..llm.pricing import usage_line
from ..results import ScenarioOutcome, SuiteResult


def _trace(outcome: ScenarioOutcome) -> str:
    if outcome.result is None:
        return ""
    lines = [
        f"{s.index}. {s.kind} {json.dumps({k: v for k, v in s.action.items() if k not in ('action', 'thought')}, ensure_ascii=False)} -> {s.outcome}"
        for s in outcome.result.steps
    ]
    return t("junit.steps") + "\n" + "\n".join(lines)


def _case(outcome: ScenarioOutcome) -> ET.Element:
    case = ET.Element("testcase", classname="plainproof", name=outcome.name, time=f"{outcome.duration_s:.1f}")
    status = outcome.status
    out = []
    if status == "error":
        error = ET.SubElement(case, "error", message=outcome.reason)
        error.text = outcome.explanation()
    elif status in ("failed", "unexpected-pass"):
        if status == "unexpected-pass":
            message, detail = t("junit.unexpected_pass"), outcome.reason
        else:
            message = outcome.diagnosis.summary if outcome.diagnosis else outcome.reason
            detail = outcome.explanation()
            if outcome.diagnosis and outcome.diagnosis.details:
                detail += f"\n\n{t('junit.details')}\n{outcome.diagnosis.details}"
        failure = ET.SubElement(case, "failure", message=message)
        failure.text = "\n\n".join(part for part in (detail, _trace(outcome)) if part)
    elif status == "expected-failure":
        out.append(t("junit.expected_failure", reason=outcome.reason))
    if outcome.usage:
        out.append(t("log.cost", line=usage_line(outcome.usage)))
    if out:
        ET.SubElement(case, "system-out").text = "\n".join(out)
    return case


def write_junit(suite: SuiteResult, path: Path) -> None:
    statuses = [o.status for o in suite.outcomes]
    root = ET.Element(
        "testsuite",
        name="plainproof",
        tests=str(len(statuses)),
        failures=str(sum(s in ("failed", "unexpected-pass") for s in statuses)),
        errors=str(statuses.count("error")),
        time=f"{suite.duration_s:.1f}",
    )
    root.extend(_case(o) for o in suite.outcomes)
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
