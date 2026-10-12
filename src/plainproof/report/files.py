"""The files written next to each scenario's screenshots: report.json and report.md."""

from __future__ import annotations

import json
from pathlib import Path

from ..i18n import t
from ..llm.pricing import usage_line
from ..results import RunResult


def _verdict(result: RunResult) -> str:
    return {True: t("verdict.passed"), False: t("verdict.failed"), None: t("verdict.unknown")}[result.success]


def write_run_files(result: RunResult, run_dir: Path, name: str) -> None:
    """``report.json`` (everything, for programs and report updates) and ``report.md`` (for humans)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# {name}: {_verdict(result)}",
        "",
        f"**{t('ui.scenario')}:**",
        "",
        *[f"> {line}" for line in result.scenario.splitlines()],
        "",
        f"**{t('ui.model')}:** {result.model}",
        f"**{t('ui.started')}:** {result.started_at} / {result.finished_at}",
        f"**{t('ui.cost')}:** {usage_line(result.usage)}",
        f"**{t('ui.verdict')}:** {result.reason}",
    ]
    if result.diagnosis:
        lines += [
            "",
            f"**{t('ui.explanation')}:** {result.diagnosis.summary}",
            f"**{t('ui.cause')}:** {t('cause.' + result.diagnosis.cause)}",
            f"**{t('ui.technical')}:** {result.diagnosis.details}",
        ]
    if result.plan:
        lines += ["", f"## {t('ui.plan')}", ""]
        lines += [
            f"{n}. {p.text}" + (f" *({t('ui.plan_verify')})*" if p.verify else "") for n, p in enumerate(result.plan, 1)
        ]
    lines += ["", f"## {t('ui.actions')}", ""]
    for step in result.steps:
        params = {k: v for k, v in step.action.items() if k != "thought"}
        lines += [
            f"### {t('ui.action')} {step.index}: `{step.kind}`",
            f"- URL: {step.url}",
            f"- {t('ui.thought')}: {step.thought}",
            f"- `{json.dumps(params, ensure_ascii=False)}`",
            f"- {t('ui.result')}: {step.outcome}",
        ]
        if step.action_screenshot or step.screenshot:
            lines.append(f"- ![action {step.index}]({step.action_screenshot or step.screenshot})")
        lines.append("")
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
