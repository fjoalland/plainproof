"""The whole tool, as a user runs it: the `plainproof` command on a local web page, with a real
Chromium and a scripted model. Run in subprocesses (Playwright's sync API allows one instance
per thread, and this test session already holds one)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ORDER_FORM = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Order form</title></head>
<body>
  <h1>New order</h1>
  <label for="name">Name</label> <input id="name">
  <label for="size">Size</label> <select id="size"><option>S</option><option>M</option><option>L</option></select>
  <label><input type="radio" name="box" id="gift"> Gift wrap</label>
  <label><input type="radio" name="box" id="plain"__PLAIN__> Plain box</label>
  <button onclick="document.getElementById('out').textContent =
    'Order received for ' + document.getElementById('name').value + ', size ' + document.getElementById('size').value">
    Send the order</button>
  <p id="out" role="status"></p>
</body></html>
"""

ANSWERS = [
    {"step": 1, "thought": "Type the customer name", "action": "type", "label": "Name", "text": "Ada"},
    {"step": 1, "thought": "Pick the size", "action": "select", "label": "Size", "option": "M"},
    {"step": 1, "thought": "No gift wrapping", "action": "click", "label": "Plain box"},
    {"step": 1, "thought": "Send it", "action": "click", "label": "Send the order"},
    {"step": 1, "thought": "Check the confirmation", "action": "check", "text": "Order received for Ada"},
    {"step": 1, "action": "finish", "success": True, "reason": "The order was received."},
]


def plainproof(cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "plainproof", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env={**os.environ, "COLUMNS": "200", "PYTHONIOENCODING": "utf-8", **(env or {})},
    )


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, str]:
    app = tmp_path / "app" / "order.html"
    app.parent.mkdir()
    app.write_text(ORDER_FORM.replace("__PLAIN__", ""), encoding="utf-8")
    scenarios = tmp_path / "e2e"
    scenarios.mkdir()
    (scenarios / "01-order.txt").write_text(
        "# An order is confirmed.\nI order a size M for Ada, in a plain box, and I check that the order is received.",
        encoding="utf-8",
    )
    (tmp_path / "answers.json").write_text(json.dumps(ANSWERS), encoding="utf-8")
    return tmp_path, app.as_uri()


def test_record_with_a_model_then_replay_without_one(project: tuple[Path, str]) -> None:
    root, url = project
    first = plainproof(
        root,
        "run",
        "e2e",
        "--model",
        "scripted:answers.json",
        "--url",
        url,
        "--no-interpret",
        "--no-diagnose",
        "--out",
        "report",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    run_dir = root / "report" / "01-order"
    assert {"report.html", "report.json", "final.png", "step_01.png", "step_01_action.png"} <= {
        p.name for p in run_dir.iterdir()
    }
    assert (run_dir / "video.webm").stat().st_size > 0
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["success"] is True
    assert report["steps"][4]["result"].startswith('CHECK OK: "Order received for Ada"')
    assert (root / "e2e" / "recordings" / "01-order.json").is_file()

    replayed = plainproof(root, "replay", "e2e", "--url", url, "--out", "replayed", "--no-video")
    assert replayed.returncode == 0, replayed.stdout + replayed.stderr
    assert json.loads((root / "replayed" / "summary.json").read_text(encoding="utf-8"))["passed"] == 1


def test_a_replay_never_changes_data_that_changed_since_the_recording(project: tuple[Path, str]) -> None:
    root, url = project
    assert (
        plainproof(
            root,
            "run",
            "e2e",
            "--model",
            "scripted:answers.json",
            "--url",
            url,
            "--no-interpret",
            "--no-diagnose",
            "--out",
            "report",
            "--no-video",
        ).returncode
        == 0
    )
    (root / "app" / "order.html").write_text(ORDER_FORM.replace("__PLAIN__", " checked"), encoding="utf-8")
    replayed = plainproof(root, "replay", "e2e", "--url", url, "--out", "replayed", "--no-video")
    assert replayed.returncode == 1
    assert '"Plain box" was unchecked when recorded and is checked now' in replayed.stdout


def test_the_generated_playwright_test_runs_on_its_own(project: tuple[Path, str]) -> None:
    root, url = project
    assert (
        plainproof(
            root,
            "run",
            "e2e",
            "--model",
            "scripted:answers.json",
            "--url",
            url,
            "--no-interpret",
            "--no-diagnose",
            "--out",
            "report",
            "--no-video",
        ).returncode
        == 0
    )
    generated = root / "e2e" / "recordings" / "test_01_order.py"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(generated), "-q", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env={**os.environ, "PLAINPROOF_URL": url},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 passed" in done.stdout
