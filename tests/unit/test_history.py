"""Campaigns: the runs of a test project kept over time, and a page comparing their verdicts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from plainproof import history
from plainproof.history import (
    Campaign,
    build,
    campaign_folder,
    detect_version,
    git_info,
    keep_budget,
    load_campaigns,
    pin,
    save_meta,
    verdict,
)


def scenario(name: str, status: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "conforms": status in ("passed", "expected-failure"),
        "scenario": f"text of {name}",
        "reason": f"reason of {name}",
        "report": f"{name}/report.html",
    }


def make_campaign(
    root: Path, cid: str, date: str, label: str, statuses: dict[str, str], *, size: int = 0, **meta: Any
) -> Path:
    folder = root / "campaigns" / cid
    (folder / "01").mkdir(parents=True)
    (folder / "summary.json").write_text(
        json.dumps(
            {
                "started_at": date,
                "finished_at": date.replace(":00", ":30", 1),
                "usage": {"cost_usd": 0.5},
                "scenarios": [scenario(name, status) for name, status in statuses.items()],
            }
        ),
        encoding="utf-8",
    )
    save_meta(folder, id=cid, date=date, label=label, model="anthropic:claude-sonnet-5-5", mode="model", **meta)
    (folder / "01" / "report.html").write_text(
        '<main><a href="step_01_action.png" target="_blank"><img src="step_01_action.png" alt="x"></a></main>',
        encoding="utf-8",
    )
    if size:
        (folder / "01" / "step_01_action.png").write_bytes(b"x" * size)
        (folder / "01" / "video.webm").write_bytes(b"v" * 10)
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    make_campaign(
        tmp_path,
        "2026-10-01_1000",
        "2026-10-01T10:00:00",
        "v1 · Java 17",
        {"01-login": "passed", "02-orders": "failed"},
    )
    make_campaign(
        tmp_path,
        "2026-10-08_1000",
        "2026-10-08T10:00:00",
        "v2 · Java 21",
        {"01-login": "passed", "02-orders": "passed", "03-canary": "expected-failure"},
        note="after migration",
    )
    return tmp_path


def test_verdicts() -> None:
    assert verdict({"status": "passed"}) == "ok"
    assert verdict({"status": "failed"}) == "ko"
    assert verdict({"status": "error"}) == "ko"
    assert verdict({"status": "expected-failure"}) == "ok-expected"
    assert verdict({"status": "unexpected-pass"}) == "ko-expected"


def test_campaigns_are_loaded_latest_first(root: Path) -> None:
    (root / "campaigns" / "incomplete").mkdir()
    campaigns = load_campaigns(root)
    assert [c.id for c in campaigns] == ["2026-10-08_1000", "2026-10-01_1000"]
    latest = campaigns[0]
    assert latest.label == "v2 · Java 21"
    assert latest.conforming == 3
    assert latest.total == 3
    assert campaigns[1].non_conforming == ["02-orders"]
    assert latest.duration_s == 1800.0
    assert latest.cost_usd == 0.5


def test_the_history_page_compares_the_verdicts(root: Path) -> None:
    build(root)
    page = (root / "index.html").read_text(encoding="utf-8")
    assert "Latest campaign on 2026-10-08 10:00, v2 · Java 21: 3 / 3 scenarios conform." in page
    assert 'href="campaigns/2026-10-01_1000/02-orders/report.html"' in page
    assert "after migration" in page
    assert page.count('class="cell none"') == 1, "03-canary did not exist in the first campaign"
    data = json.loads((root / "history.json").read_text(encoding="utf-8"))
    assert data[0]["verdicts"] == {"01-login": "ok", "02-orders": "ok", "03-canary": "ok-expected"}


def test_the_title_is_kept_between_rebuilds(root: Path) -> None:
    build(root, title="Shop <history>")
    build(root)
    page = (root / "index.html").read_text(encoding="utf-8")
    assert "<title>Shop &lt;history&gt;</title>" in page


def test_an_empty_history(tmp_path: Path) -> None:
    build(tmp_path)
    assert "No campaign yet." in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_the_budget_lightens_then_deletes_the_oldest_campaigns(tmp_path: Path) -> None:
    make_campaign(tmp_path, "2026-01-01_1000", "2026-01-01T10:00:00", "v1", {"a": "passed"}, size=4000)
    make_campaign(tmp_path, "2026-02-01_1000", "2026-02-01T10:00:00", "v1", {"a": "passed"}, size=4000, pinned=True)
    make_campaign(tmp_path, "2026-03-01_1000", "2026-03-01T10:00:00", "v1", {"a": "passed"}, size=4000)
    make_campaign(tmp_path, "2026-04-01_1000", "2026-04-01T10:00:00", "v2", {"a": "passed"}, size=4000)
    campaigns = load_campaigns(tmp_path)
    log = keep_budget(campaigns, budget_bytes=2500)
    ids = [c.id for c in campaigns]
    assert "2026-04-01_1000" in ids, "the latest campaign is never touched"
    assert "2026-02-01_1000" in ids, "a pinned campaign is never deleted"
    assert "2026-01-01_1000" not in ids
    assert not (tmp_path / "campaigns" / "2026-01-01_1000").exists()
    pinned = next(c for c in campaigns if c.id == "2026-02-01_1000")
    assert pinned.lightened
    assert not list((pinned.folder / "01").glob("step_*.png"))
    assert (pinned.folder / "01" / "video.webm").exists()
    report = (pinned.folder / "01" / "report.html").read_text(encoding="utf-8")
    assert "step_01_action.png" not in report
    assert "Lightened campaign" in report
    assert any("deleted" in line for line in log)
    assert any("over budget" in line for line in log), "pinned campaigns can keep the total over budget"


def test_pin_and_unpin(root: Path) -> None:
    pin(root, "2026-10-01_1000", True)
    assert load_campaigns(root)[1].pinned
    pin(root, "2026-10-01_1000", False)
    assert not load_campaigns(root)[1].pinned
    with pytest.raises(FileNotFoundError, match="nope"):
        pin(root, "nope", True)


def test_campaign_folder_is_named_after_its_date(tmp_path: Path) -> None:
    from datetime import datetime

    assert campaign_folder(tmp_path, datetime(2026, 10, 12, 9, 5)) == tmp_path / "campaigns" / "2026-10-12_0905"


def test_save_meta_completes_without_erasing(tmp_path: Path) -> None:
    save_meta(tmp_path, id="x", note="first", pinned=None)
    save_meta(tmp_path, note=None, model="m")
    assert json.loads((tmp_path / "campaign.json").read_text(encoding="utf-8")) == {
        "id": "x",
        "note": "first",
        "model": "m",
    }


class TestVersionDetection:
    @pytest.mark.parametrize(
        ("file", "content", "version"),
        [
            ("package.json", '{"name": "shop", "version": "3.2.1"}', "3.2.1"),
            ("pyproject.toml", '[project]\nname = "shop"\nversion = "1.4.0"\n', "1.4.0"),
            (
                "pom.xml",
                "<project><parent><version>9.9</version></parent><version>2.0.0-SNAPSHOT</version></project>",
                "2.0.0-SNAPSHOT",
            ),
            ("build.gradle.kts", 'group = "shop"\nversion = "5.1"\n', "5.1"),
            ("build.gradle", "version '0.9.1'\n", "0.9.1"),
        ],
    )
    def test_manifests(self, tmp_path: Path, file: str, content: str, version: str) -> None:
        (tmp_path / file).write_text(content, encoding="utf-8")
        assert detect_version(tmp_path) == version

    def test_none(self, tmp_path: Path) -> None:
        assert detect_version(tmp_path) == ""


def test_git_info_reads_branch_commit_and_version(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-b", "feature/x")
    (tmp_path / "package.json").write_text('{"version": "1.0.0"}', encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-m", "init")
    info = git_info(tmp_path)
    assert info["branch"] == "feature/x"
    assert len(info["commit"]) >= 7
    assert info["version"] == "1.0.0"
    assert git_info(None) == {}


def test_compress_needs_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(history.shutil, "which", lambda _: None)
    assert history.compress(tmp_path) is None


def test_campaign_from_folder_tolerates_missing_numbers(tmp_path: Path) -> None:
    folder = make_campaign(tmp_path, "c", "2026-10-01T10:00:00", "v1", {"a": "passed"})
    (folder / "summary.json").write_text(json.dumps({"scenarios": []}), encoding="utf-8")
    campaign = Campaign.load(folder)
    assert campaign is not None
    assert campaign.duration_s is None
    assert campaign.cost_usd is None
    assert campaign.total == 0
