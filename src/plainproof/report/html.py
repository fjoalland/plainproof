"""The HTML report: a step-by-step page per scenario and an overview of the suite.

Plain static pages (no build step, no external resource, light and dark themes): they open
from disk, from a CI artifact or from any static host. Screenshots and videos are referenced
by relative path, so the output folder is published as a whole. Every text that comes from a
scenario, a page or a model is escaped.
"""

from __future__ import annotations

import json
import posixpath
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader

from .. import __version__
from ..i18n import get_language, t
from ..llm.pricing import format_cost, format_tokens
from ..results import ScenarioOutcome, Step, SuiteResult

_ENV = Environment(
    loader=PackageLoader("plainproof.report", "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
# Globals reach imported macros too; t() follows the current language at render time.
_ENV.globals.update(t=t, version=__version__)
_CONFORMING = ("passed", "expected-failure")


@dataclass(frozen=True)
class NavItem:
    """A scenario in the side navigation."""

    name: str
    href: str
    status: str
    duration_s: float


def _css(status: str) -> str:
    return "ok" if status in _CONFORMING else "ko"


def format_seconds(seconds: float, decimals: int = 0) -> str:
    text = f"{seconds:.{decimals}f}"
    return (text.replace(".", ",") if get_language() == "fr" else text) + " s"


def _day_time(iso: str) -> tuple[str, str]:
    try:
        moment = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or "", ""
    day = moment.strftime("%d/%m/%Y") if get_language() == "fr" else moment.strftime("%Y-%m-%d")
    return day, moment.strftime("%H:%M:%S")


def render_page(template: str, **context: Any) -> str:
    """Render one of the report templates in the current language."""
    return _ENV.get_template(template).render(lang=get_language(), **context)


def _file(run_dir: Path, name: str, prefix: str = "") -> str:
    """``prefix + name`` when the file exists in ``run_dir``, else ""."""
    return f"{prefix}{name}" if name and (run_dir / name).is_file() else ""


def _verdict(outcome: ScenarioOutcome) -> dict[str, Any]:
    technical = ""
    if not outcome.passed:
        details = outcome.diagnosis.details if outcome.diagnosis else ""
        technical = "\n".join(part for part in (details, outcome.explanation(technical_only=True)) if part)
    return {
        "ok": outcome.conforms,
        "title": t("ui.verdict"),
        "reason": outcome.reason,
        "diagnosis": outcome.diagnosis if not outcome.passed else None,
        "technical": technical,
    }


def _step(step: Step, run_dir: Path) -> dict[str, Any]:
    failed = bool(step.error) or step.failed_check
    css = "ko" if failed else "end" if step.kind == "finish" else "ok"
    params = {k: v for k, v in step.action.items() if k not in ("action", "thought")}
    return {
        "index": step.index,
        "kind": step.kind or "?",
        "params": json.dumps(params, ensure_ascii=False) if params else "",
        "outcome": step.outcome,
        "css": css,
        "icon": {"ko": "x", "end": "flag", "ok": "check"}[css],
        "open": failed or step.kind == "finish",
        "duration": format_seconds(step.duration_ms / 1000, 1),
        "action_image": _file(run_dir, step.action_screenshot),
        "input_image": _file(run_dir, step.screenshot),
        "url": step.url,
        "url_after": step.url_after if step.url_after and step.url_after != step.url else "",
        "thought": step.thought,
    }


def _panel(outcome: ScenarioOutcome) -> list[tuple[str, str]]:
    result = outcome.result
    steps = result.steps if result else []
    rows = [
        (t("ui.model"), result.model if result else "—"),
        (t("ui.actions"), str(len(steps))),
        (t("ui.action_errors"), str(sum(1 for s in steps if s.error))),
        (t("ui.duration"), format_seconds(outcome.duration_s or (result.duration_ms / 1000 if result else 0), 1)),
    ]
    usage = outcome.usage
    if usage is not None:
        rows += [
            (t("ui.cost"), format_cost(usage.cost_usd)),
            (t("ui.tokens"), f"{format_tokens(usage.total_input_tokens)} / {format_tokens(usage.output_tokens)}"),
            (t("ui.calls"), str(usage.calls)),
        ]
    if result and result.started_at:
        rows.append((t("ui.started"), " ".join(_day_time(result.started_at)).strip()))
    return rows


def _nav(items: Sequence[NavItem], current: str) -> list[dict[str, Any]]:
    return [
        {
            "name": i.name,
            "href": i.href,
            "css": _css(i.status),
            "duration": format_seconds(i.duration_s),
            "current": i.name == current,
        }
        for i in items
    ]


def run_page_html(
    outcome: ScenarioOutcome, run_dir: Path, nav: Sequence[NavItem] | None = None, label: str = ""
) -> str:
    result = outcome.result
    status_label = t(f"status.{outcome.status}")
    names = [item.name for item in nav or []]
    position = (names.index(outcome.name) + 1, len(names)) if outcome.name in names else None
    previous = following = None
    if position is not None and nav:
        previous = nav[position[0] - 2] if position[0] > 1 else None
        following = nav[position[0]] if position[0] < len(nav) else None
    plan = [
        {
            "text": p.text,
            "verify": p.verify,
            "origin": t("ui.plan_line", n=p.source) if p.source else t("ui.plan_added"),
        }
        for p in (result.plan or [] if result else [])
    ]
    steps = result.steps if result else []
    day, time = _day_time(result.started_at) if result else ("", "")
    return render_page(
        "run.html.j2",
        page="run",
        root="../",
        title=f"{outcome.name} · {status_label} · plainproof",
        label=label,
        day=day,
        time=time,
        model=result.model if result else "",
        nav=_nav(nav or [], outcome.name),
        files=[("report.json", "report.json", "code"), ("report.md", "report.md", "file")],
        name=outcome.name,
        css=_css(outcome.status),
        status_label=status_label,
        description=outcome.description,
        expected_failure=outcome.expected_failure,
        position=position,
        previous=previous,
        following=following,
        video=(run_dir / "video.webm").is_file(),
        final=(run_dir / "final.png").is_file(),
        source=outcome.source,
        plan=plan,
        outcome=_verdict(outcome),
        panel=_panel(outcome),
        steps=[_step(s, run_dir) for s in steps],
        last_url=(steps[-1].url_after or steps[-1].url) if steps else "",
    )


def write_run_page(
    outcome: ScenarioOutcome, run_dir: Path, nav: Sequence[NavItem] | None = None, label: str = ""
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "report.html"
    path.write_text(run_page_html(outcome, run_dir, nav, label), encoding="utf-8")
    return path


def _source_folder(suite: SuiteResult) -> str:
    folders = [posixpath.dirname(o.file) for o in suite.outcomes if o.file]
    if not folders:
        return ""
    common = posixpath.commonpath(folders) if all(f for f in folders) else ""
    return f"{common}/" if common else ""


def write_index(suite: SuiteResult, out_dir: Path) -> Path:
    """The suite overview; every scenario page is (re)written with the navigation between them."""
    nav = [NavItem(o.name, f"../{o.name}/report.html", o.status, o.duration_s) for o in suite.outcomes]
    for outcome in suite.outcomes:
        write_run_page(outcome, out_dir / outcome.name, nav, suite.label)
    if suite.ok:
        suite_label = t("ui.suite_passed")
    else:
        suite_label = t("ui.failures_one") if suite.failed == 1 else t("ui.failures_many", n=suite.failed)
    cards = []
    for outcome in suite.outcomes:
        run_dir = out_dir / outcome.name
        cards.append(
            {
                "name": outcome.name,
                "href": f"{outcome.name}/report.html",
                "css": _css(outcome.status),
                "status_label": t(f"status.{outcome.status}"),
                "actions": len(outcome.result.steps) if outcome.result else 0,
                "duration": format_seconds(outcome.duration_s),
                "cost": format_cost(outcome.usage.cost_usd) if outcome.usage else "—",
                "description": outcome.description,
                "source": outcome.source,
                "outcome": _verdict(outcome),
                "final": _file(run_dir, "final.png", f"{outcome.name}/"),
                "video": _file(run_dir, "video.webm", f"{outcome.name}/"),
            }
        )
    usage = suite.usage
    day, time = _day_time(suite.started_at)
    html = render_page(
        "index.html.j2",
        page="index",
        root="",
        title=f"{t('ui.suite_results')} · {suite_label} · plainproof",
        label=suite.label,
        day=day,
        time=time,
        model=suite.model,
        nav=_nav([NavItem(i.name, f"{i.name}/report.html", i.status, i.duration_s) for i in nav], ""),
        files=[("junit.xml", "junit.xml", "file"), ("summary.json", "summary.json", "code")],
        suite_css="ok" if suite.ok else "ko",
        suite_label=suite_label,
        intro=t("ui.intro_one") if suite.total == 1 else t("ui.intro_many", n=suite.total),
        source=_source_folder(suite),
        stats=[
            (suite.total, t("ui.stat_scenarios"), ""),
            (suite.passed, t("ui.stat_passed"), "ok"),
            (suite.failed, t("ui.stat_failed"), "ko" if suite.failed else ""),
            (format_seconds(suite.duration_s), t("ui.stat_duration"), ""),
            (format_cost(usage.cost_usd) if usage.calls else "—", t("ui.stat_cost"), ""),
        ],
        total=suite.total,
        passed=suite.passed,
        failed=suite.failed,
        cards=cards,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
