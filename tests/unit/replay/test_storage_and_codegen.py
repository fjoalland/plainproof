"""Where recordings live, and the plain Playwright test generated from each one."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from plainproof.replay.codegen import accessible_name, to_pytest
from plainproof.replay.storage import RecordingMissingError, load_recording, recording_paths, write_recording
from plainproof.scenario import load_scenarios


def scenario_file(tmp_path: Path, name: str = "01-login.txt") -> Any:
    (tmp_path / name).write_text("I log in.", encoding="utf-8")
    (scenario,) = load_scenarios(str(tmp_path / name), env={})
    return scenario


class TestStorage:
    def test_recordings_sit_next_to_the_scenario(self, tmp_path: Path) -> None:
        paths = recording_paths(scenario_file(tmp_path, "02-new order.txt"))
        assert paths == (
            tmp_path / "recordings" / "02-new order.json",
            tmp_path / "recordings" / "test_02_new_order.py",
        )

    def test_an_inline_scenario_has_nowhere_to_keep_a_recording(self) -> None:
        (inline,) = load_scenarios("Open the app", env={})
        assert recording_paths(inline) is None
        assert write_recording({"steps": []}, inline) is None
        with pytest.raises(RecordingMissingError, match="inline"):
            load_recording(inline)

    def test_write_then_load(self, tmp_path: Path) -> None:
        scenario = scenario_file(tmp_path)
        recording = {"recorded_at": "2026-10-12T10:00:00", "start_url": "http://app/", "steps": []}
        written = write_recording(recording, scenario)
        assert written == tmp_path / "recordings" / "01-login.json"
        assert load_recording(scenario) == recording
        assert (tmp_path / "recordings" / "test_01_login.py").is_file()

    def test_a_missing_recording_says_how_to_make_one(self, tmp_path: Path) -> None:
        with pytest.raises(RecordingMissingError, match="run it once with a model"):
            load_recording(scenario_file(tmp_path))

    def test_an_unreadable_recording_is_reported(self, tmp_path: Path) -> None:
        scenario = scenario_file(tmp_path)
        (tmp_path / "recordings").mkdir()
        (tmp_path / "recordings" / "01-login.json").write_text("{broken", encoding="utf-8")
        with pytest.raises(RecordingMissingError, match="cannot be read"):
            load_recording(scenario)


RECORDING = {
    "recorded_at": "2026-10-12T10:00:00",
    "start_url": "http://app/",
    "steps": [
        {
            "action": "type",
            "target": {"tag": "input", "type": "password", "label": "Password", "nth": 0},
            "text": "${APP_PASSWORD}",
            "submit": True,
        },
        {"action": "click", "target": {"tag": "input", "type": "radio", "label": "No", "nth": 0, "checked": False}},
        {
            "action": "select",
            "target": {"tag": "div", "role": "combobox", "label": "Reason", "nth": 0},
            "option": "None",
        },
        {"action": "select", "target": {"tag": "select", "label": "Size", "nth": 1}, "option": "M"},
        {"action": "check", "text": "Order created", "meaning": "a confirmation"},
        {"action": "check", "url": "/orders", "absent": True},
        {"action": "check", "meaning": "no 2050 row", "absent": True, "replayable": False},
        {"action": "note", "note": "origin = Yes"},
        {
            "action": "click",
            "target": {"tag": "button", "label": "Delete order 61", "nth": 0, "row": "61 Acme 01/12/2050 10/01/2051"},
        },
        {"action": "click", "target": {"tag": "a", "text": "Help", "nth": 2}},
        {"action": "click", "target": {"tag": "div", "text": "Card", "nth": 0}},
        {"action": "click", "target": {"tag": "span", "nth": 0}},
        {"action": "press", "key": "Escape"},
        {"action": "scroll", "direction": "up"},
        {"action": "wait", "seconds": 1.5},
        {"action": "back"},
        {"action": "navigate", "url": "https://app.test/next"},
    ],
}


class TestCodegen:
    def code(self, tmp_path: Path) -> str:
        return to_pytest(RECORDING, scenario_file(tmp_path))

    def test_is_valid_python_named_after_the_scenario(self, tmp_path: Path) -> None:
        code = self.code(tmp_path)
        compile(code, "generated.py", "exec")
        assert "def test_01_login(page: Page) -> None:" in code
        assert "URL = os.environ.get(\"PLAINPROOF_URL\", 'http://app/')" in code

    def test_actions(self, tmp_path: Path) -> None:
        code = self.code(tmp_path)
        assert "page.get_by_role('textbox', name='Password').nth(0).fill(_v('${APP_PASSWORD}'))" in code
        assert "page.get_by_role('textbox', name='Password').nth(0).press(\"Enter\")" in code
        assert "expect(page.get_by_role('radio', name='No').nth(0)).not_to_be_checked()" in code
        assert "page.get_by_role(\"option\", name='None').click()" in code, "custom dropdown: open, then pick"
        assert "page.get_by_role('combobox', name='Size').nth(1).select_option(label='M')" in code
        assert "page.get_by_role('link', name='Help').nth(2).click()" in code
        assert "page.get_by_text('Card', exact=True).nth(0).click()" in code, "no role: found by its text"
        assert "page.locator('span').nth(0)" in code
        assert "to adapt" in code
        for line in (
            "page.keyboard.press('Escape')",
            "page.mouse.wheel(0, -600)",
            "page.wait_for_timeout(1500)",
            "page.go_back()",
            "page.goto('https://app.test/next')",
        ):
            assert line in code

    def test_checks(self, tmp_path: Path) -> None:
        code = self.code(tmp_path)
        assert (
            "    # a confirmation\n    expect(page.locator(\"body\")).to_contain_text('Order created', ignore_case=True)"
            in code
        )
        assert "expect(page).not_to_have_url(re.compile(re.escape('/orders')))" in code
        assert "# not verifiable without a model: no 2050 row" in code
        assert "# note: origin = Yes" in code

    def test_a_row_button_is_found_by_the_dates_of_its_row(self, tmp_path: Path) -> None:
        line = next(code for code in self.code(tmp_path).splitlines() if 'get_by_role("row")' in code)
        assert line.strip().startswith(
            "page.get_by_role(\"row\").filter(has_text='01/12/2050').filter(has_text='10/01/2051')"
        )
        pattern = re.search(r"re\.compile\('(.*)'\)\)\.click", line)
        assert pattern is not None
        regex = pattern.group(1).replace("\\\\", "\\")
        assert re.fullmatch(regex, "Delete order 63"), "an identifier in the name may differ from one run to the next"
        assert not re.fullmatch(regex, "Delete order")

    @pytest.mark.parametrize(
        ("target", "role", "expected"),
        [
            ({"tag": "input", "label": "User name or email *"}, "textbox", "User name or email"),
            ({"tag": "input", "label": "End date * (Pick a date)"}, "combobox", "End date"),
            ({"tag": "button", "label": "View (2)"}, "button", "View (2)"),
        ],
    )
    def test_accessible_name_keeps_the_core_of_a_field_label(
        self, target: dict[str, Any], role: str, expected: str
    ) -> None:
        assert accessible_name(target, role) == expected

    def test_written_file_is_the_generated_code(self, tmp_path: Path) -> None:
        scenario = scenario_file(tmp_path)
        write_recording(RECORDING, scenario)
        written = (tmp_path / "recordings" / "test_01_login.py").read_text(encoding="utf-8")
        assert written == to_pytest(RECORDING, scenario)
        assert json.loads((tmp_path / "recordings" / "01-login.json").read_text(encoding="utf-8")) == RECORDING
