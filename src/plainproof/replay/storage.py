"""Where recordings live: ``recordings/`` next to each scenario.

scenarios/
├── 01-login.txt
└── recordings/
    ├── 01-login.json          replayed by `plainproof replay`
    └── test_01_login.py       the same actions as a plain Playwright test (pytest)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..errors import PlainproofError
from ..i18n import t
from ..scenario import RECORDINGS_DIR, Scenario
from .codegen import to_pytest


class RecordingMissingError(PlainproofError):
    """A scenario replayed without a usable recording."""


def test_function_name(stem: str) -> str:
    return re.sub(r"\W+", "_", stem).strip("_").lower()


def recording_paths(scenario: Scenario) -> tuple[Path, Path] | None:
    """(recording, generated test) next to the scenario file; None for an inline scenario.
    The test is named ``test_<scenario>.py`` so that ``pytest recordings/`` collects it."""
    if scenario.path is None:
        return None
    folder = scenario.path.parent / RECORDINGS_DIR
    return folder / f"{scenario.path.stem}.json", folder / f"test_{test_function_name(scenario.path.stem)}.py"


def write_recording(recording: dict[str, Any], scenario: Scenario) -> Path | None:
    paths = recording_paths(scenario)
    if paths is None:
        return None
    json_path, test_path = paths
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(recording, ensure_ascii=False, indent=2), encoding="utf-8")
    test_path.write_text(to_pytest(recording, scenario), encoding="utf-8")
    return json_path


def load_recording(scenario: Scenario) -> dict[str, Any]:
    paths = recording_paths(scenario)
    if paths is None or not paths[0].is_file():
        raise RecordingMissingError(t("replay.missing", path=paths[0].as_posix() if paths else scenario.name))
    try:
        data: dict[str, Any] = json.loads(paths[0].read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise RecordingMissingError(f"{paths[0].name} cannot be read: {err}") from None
    return data
