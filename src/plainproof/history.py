"""Campaigns: the runs of a test project kept over time, and a page comparing their verdicts
from one run (or one version of the application) to the next.

    my-app-tests/
    ├── scenarios/                    the .txt scenarios, context.md, recordings/
    └── history/                      `plainproof run --campaign history`
        ├── index.html                every campaign, verdicts compared scenario by scenario
        ├── history.json              the same, for programs
        └── campaigns/
            └── 2026-10-12_0930/      a suite report, plus campaign.json (label, model, code version...)

The folder is a static site. Its size is kept under a budget (static hosts limit sites, GitLab
Pages to 100 MB): the oldest campaigns are first lightened (step screenshots removed; the video,
the final screenshot and the report text stay), then the oldest unpinned ones are deleted. The
latest campaign is never touched. Pin the last campaign of a version to keep it as a reference.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .browser.video import reencode
from .i18n import get_language, t
from .llm.pricing import format_cost
from .report.html import format_seconds, render_page

CAMPAIGNS_DIR = "campaigns"
META_FILE = "campaign.json"
TITLE_FILE = "title.txt"
DEFAULT_BUDGET_MB = 90.0
COMPARED_COLUMNS = 15

# A campaign's videos go down to 960 px and 3 frames per second; screenshots to 96 colours.
FFMPEG_VIDEO = (
    "-vf",
    "scale=960:-2",
    "-c:v",
    "libvpx-vp9",
    "-crf",
    "44",
    "-b:v",
    "0",
    "-r",
    "3",
    "-row-mt",
    "1",
    "-deadline",
    "good",
    "-cpu-used",
    "4",
    "-an",
)
FFMPEG_PNG = (
    "-vf",
    "split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];[b][p]paletteuse=dither=none",
    "-pix_fmt",
    "pal8",
)

_STEP_IMAGE_LINK = re.compile(r'<a href="step_\d+(?:_action)?\.png"[^>]*>\s*<img[^>]*>\s*</a>')
_SYMBOLS = {"ok": "✓", "ko": "✗", "ok-expected": "✓", "ko-expected": "!"}


def verdict(scenario: dict[str, Any]) -> str:
    """ok, ko, ok-expected (a canary failed, as it should) or ko-expected (a canary passed)."""
    status = scenario.get("status")
    if status == "expected-failure":
        return "ok-expected"
    if status == "unexpected-pass":
        return "ko-expected"
    return "ok" if status == "passed" else "ko"


def size_of(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class Campaign:
    folder: Path
    meta: dict[str, Any]
    summary: dict[str, Any]
    size: int = 0
    scenarios: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, folder: Path) -> Campaign | None:
        """A complete campaign (campaign.json and summary.json), or None."""
        meta, summary = _read_json(folder / META_FILE), _read_json(folder / "summary.json")
        if not meta or not summary:
            return None
        scenarios = [s for s in summary.get("scenarios", []) if isinstance(s, dict)]
        return cls(folder=folder, meta=meta, summary=summary, size=size_of(folder), scenarios=scenarios)

    @property
    def id(self) -> str:
        return str(self.meta.get("id") or self.folder.name)

    @property
    def date(self) -> str:
        return str(self.meta.get("date") or self.summary.get("started_at") or "")

    @property
    def label(self) -> str:
        return str(self.meta.get("label") or "—")

    @property
    def pinned(self) -> bool:
        return bool(self.meta.get("pinned"))

    @property
    def lightened(self) -> bool:
        return bool(self.meta.get("lightened"))

    @property
    def total(self) -> int:
        return len(self.scenarios)

    @property
    def conforming(self) -> int:
        return sum(verdict(s) in ("ok", "ok-expected") for s in self.scenarios)

    @property
    def non_conforming(self) -> list[str]:
        return [str(s.get("name")) for s in self.scenarios if verdict(s) not in ("ok", "ok-expected")]

    @property
    def duration_s(self) -> float | None:
        start, end = self.summary.get("started_at"), self.summary.get("finished_at")
        if not isinstance(start, str) or not isinstance(end, str):
            return None
        try:
            return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        except ValueError:
            return None

    @property
    def cost_usd(self) -> float | None:
        cost = (self.summary.get("usage") or {}).get("cost_usd")
        return None if cost is None else float(cost)

    def verdicts(self) -> dict[str, str]:
        return {str(s.get("name")): verdict(s) for s in self.scenarios}


def campaign_folder(root: Path, started: datetime) -> Path:
    return root / CAMPAIGNS_DIR / started.strftime("%Y-%m-%d_%H%M")


def load_campaigns(root: Path) -> list[Campaign]:
    """Complete campaigns, latest first."""
    folders = sorted((root / CAMPAIGNS_DIR).glob("*/")) if (root / CAMPAIGNS_DIR).is_dir() else []
    campaigns = [c for c in (Campaign.load(f) for f in folders if f.is_dir()) if c is not None]
    campaigns.sort(key=lambda c: c.date, reverse=True)
    return campaigns


def save_meta(folder: Path, **fields: Any) -> None:
    """Write (or complete) the campaign.json of a campaign folder; None values are left out."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / META_FILE
    data = _read_json(path)
    data.update({key: value for key, value in fields.items() if value is not None})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def pin(root: Path, campaign_id: str, value: bool) -> None:
    folder = root / CAMPAIGNS_DIR / campaign_id
    if not (folder / META_FILE).is_file():
        raise FileNotFoundError(f"Campaign not found: {campaign_id}")
    save_meta(folder, pinned=value)


# -- size ---------------------------------------------------------------------------------------
def compress(folder: Path) -> tuple[int, int] | None:
    """Videos and screenshots of a campaign made lighter: (bytes before, after), or None without ffmpeg."""
    if not shutil.which("ffmpeg"):
        return None
    before = size_of(folder)
    jobs = [(v, FFMPEG_VIDEO) for v in folder.rglob("video.webm")] + [(p, FFMPEG_PNG) for p in folder.rglob("*.png")]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        list(pool.map(lambda job: reencode(job[0], job[1]), jobs))
    return before, size_of(folder)


def lighten(campaign: Campaign) -> int:
    """Remove the step screenshots of a campaign (the video and the final screenshot stay). Returns the bytes saved."""
    saved = 0
    for shot in campaign.folder.rglob("step_*.png"):
        saved += shot.stat().st_size
        shot.unlink()
    banner = f'<p class="note" style="margin-bottom:1rem">{html_lib.escape(t("history.lightened_banner"))}</p>'
    for report in campaign.folder.rglob("report.html"):
        text = report.read_text(encoding="utf-8")
        light = _STEP_IMAGE_LINK.sub('<p class="muted">—</p>', text)
        if light != text:
            report.write_text(light.replace("<main>", "<main>" + banner, 1), encoding="utf-8")
    save_meta(campaign.folder, lightened=True)
    campaign.meta["lightened"] = True
    campaign.size = size_of(campaign.folder)
    return saved


def _mb(size: float) -> str:
    return f"{size / 1e6:.1f}"


def keep_budget(campaigns: list[Campaign], budget_bytes: int) -> list[str]:
    """Lighten, then delete, the oldest campaigns until the total fits the budget. Returns a log.
    ``campaigns`` (latest first) loses the deleted ones."""
    log: list[str] = []

    def total() -> int:
        return sum(c.size for c in campaigns)

    oldest_first = campaigns[1:][::-1]  # the latest campaign is never touched
    for campaign in oldest_first:
        if total() <= budget_bytes:
            return log
        if not campaign.lightened:
            log.append(t("history.log_lightened", id=campaign.id, mb=_mb(lighten(campaign))))
    for campaign in oldest_first:
        if total() <= budget_bytes:
            break
        if not campaign.pinned:
            shutil.rmtree(campaign.folder)
            campaigns.remove(campaign)
            log.append(t("history.log_deleted", id=campaign.id, mb=_mb(campaign.size)))
    if total() > budget_bytes:
        log.append(t("history.log_over_budget", total=_mb(total() - budget_bytes), budget=_mb(budget_bytes)))
    return log


# -- page -----------------------------------------------------------------------------------------
def _when(campaign: Campaign, pattern_en: str, pattern_fr: str) -> str:
    try:
        moment = datetime.fromisoformat(campaign.date)
    except ValueError:
        return campaign.date
    return moment.strftime(pattern_fr if get_language() == "fr" else pattern_en)


def render(campaigns: list[Campaign], title: str) -> str:
    labels: list[str] = []
    for campaign in reversed(campaigns):
        if campaign.label not in labels:
            labels.append(campaign.label)

    def tint(label: str) -> int:
        return labels.index(label) % 4

    texts: dict[str, str] = {}
    expected: dict[str, bool] = {}
    for campaign in campaigns:
        for scenario in campaign.scenarios:
            name = str(scenario.get("name"))
            texts.setdefault(name, str(scenario.get("scenario") or ""))
            expected[name] = expected.get(name, False) or verdict(scenario).endswith("expected")
    columns = campaigns[:COMPARED_COLUMNS]
    matrix = []
    for name in sorted(texts):
        cells: list[dict[str, str] | None] = []
        for campaign in columns:
            found = next((s for s in campaign.scenarios if s.get("name") == name), None)
            if found is None:
                cells.append(None)
                continue
            outcome = verdict(found)
            cells.append(
                {
                    "verdict": outcome,
                    "symbol": _SYMBOLS[outcome],
                    "href": f"{CAMPAIGNS_DIR}/{campaign.id}/{scenario.get('report') or ''}",
                    "title": f"{t('history.verdict.' + outcome)} — {scenario.get('reason') or ''}",
                }
            )
        matrix.append({"name": name, "text": texts[name], "expected": expected[name], "cells": cells})
    rows = []
    for campaign in campaigns:
        mode = str(campaign.meta.get("mode") or "model")
        rows.append(
            {
                "date": _when(campaign, "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"),
                "pinned": campaign.pinned,
                "lightened": campaign.lightened,
                "note": campaign.meta.get("note") or "",
                "label": campaign.label,
                "tint": tint(campaign.label),
                "model": campaign.meta.get("model") or "—",
                "mode": t("history.mode_replay") if mode == "replay" else t("history.mode_model"),
                "conforming": campaign.conforming,
                "total": campaign.total,
                "percent": round(100 * campaign.conforming / campaign.total) if campaign.total else 0,
                "non_conforming": ", ".join(campaign.non_conforming),
                "cost": "—" if campaign.cost_usd is None else format_cost(campaign.cost_usd),
                "duration": "—" if campaign.duration_s is None else format_seconds(campaign.duration_s),
                "size": f"{_mb(campaign.size)} MB",
                "version": campaign.meta.get("version") or "",
                "branch": campaign.meta.get("branch") or "",
                "commit": campaign.meta.get("commit") or "",
                "href": f"{CAMPAIGNS_DIR}/{campaign.id}/index.html",
            }
        )
    if campaigns:
        latest = campaigns[0]
        lead = t(
            "history.latest",
            date=_when(latest, "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"),
            label=latest.label,
            ok=latest.conforming,
            total=latest.total,
        )
    else:
        lead = t("history.none")
    return render_page(
        "history.html.j2",
        page="history",
        root="",
        title=title,
        label="",
        day="",
        time="",
        model="",
        nav=None,
        files=None,
        lead=lead,
        labels=labels,
        columns=[
            {
                "day": _when(c, "%Y-%m-%d", "%d/%m/%y"),
                "time": _when(c, "%H:%M", "%H:%M"),
                "tint": tint(c.label),
                "label": c.label,
                "model": c.meta.get("model") or "",
            }
            for c in columns
        ],
        matrix=matrix,
        campaigns=rows,
    )


def build(root: Path, budget_mb: float = DEFAULT_BUDGET_MB, title: str | None = None) -> list[str]:
    """Keep the budget, then write index.html and history.json. Returns a log."""
    root.mkdir(parents=True, exist_ok=True)
    if title:
        (root / TITLE_FILE).write_text(title, encoding="utf-8")
    elif (root / TITLE_FILE).is_file():
        title = (root / TITLE_FILE).read_text(encoding="utf-8").strip()
    campaigns = load_campaigns(root)
    log = keep_budget(campaigns, int(budget_mb * 1e6))
    (root / "index.html").write_text(render(campaigns, title or t("history.title")), encoding="utf-8")
    history = [
        {
            "id": c.id,
            "date": c.date,
            "label": c.label,
            "model": c.meta.get("model"),
            "mode": c.meta.get("mode"),
            "version": c.meta.get("version"),
            "branch": c.meta.get("branch"),
            "commit": c.meta.get("commit"),
            "pinned": c.pinned,
            "lightened": c.lightened,
            "size_bytes": c.size,
            "total": c.total,
            "conforming": c.conforming,
            "non_conforming": c.non_conforming,
            "cost_usd": c.cost_usd,
            "duration_s": c.duration_s,
            "verdicts": c.verdicts(),
        }
        for c in campaigns
    ]
    (root / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    log.append(
        t("history.log_total", n=len(campaigns), total=_mb(sum(c.size for c in campaigns)), budget=f"{budget_mb:.0f}")
    )
    return log


# -- what was tested ------------------------------------------------------------------------------
_GRADLE_VERSION = re.compile(r"""^\s*version\s*=?\s*['"]([^'"]+)['"]""", re.MULTILINE)


def detect_version(repo: Path) -> str:
    """The version declared by the application's manifest (package.json, pyproject.toml, pom.xml, Gradle)."""
    package = _read_json(repo / "package.json")
    if package.get("version"):
        return str(package["version"])
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        found = re.search(
            r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8", errors="replace"), re.MULTILINE
        )
        if found:
            return found.group(1)
    pom = repo / "pom.xml"
    if pom.is_file():
        text = re.sub(r"<parent>.*?</parent>", "", pom.read_text(encoding="utf-8", errors="replace"), flags=re.DOTALL)
        found = re.search(r"<version>([^<]+)</version>", text)
        if found:
            return found.group(1).strip()
    for gradle in ("build.gradle.kts", "build.gradle"):
        if (repo / gradle).is_file():
            found = _GRADLE_VERSION.search((repo / gradle).read_text(encoding="utf-8", errors="replace"))
            if found:
                return found.group(1)
    return ""


def git_info(repo: Path | None) -> dict[str, str]:
    """Branch, commit and version of the tested application, read (only) in its repository."""
    if repo is None:
        return {}

    def git(*args: str) -> str:
        try:
            done = subprocess.run(
                ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return done.stdout.strip() if done.returncode == 0 else ""

    return {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "version": detect_version(repo) or git("describe", "--tags", "--abbrev=0"),
    }
