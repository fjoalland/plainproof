"""Replaying a recording without any model: same browser helpers, same report, never blind."""

from pathlib import Path
from typing import Any

from plainproof.browser.model import Element
from plainproof.replay.replayer import REPLAY_MODEL, Replayer
from plainproof.results import Step
from plainproof.scenario import Scenario
from plainproof.secrets import Secrets
from tests.fakes import FakeBrowser

SCENARIO = Scenario(
    name="01-save", source="Choose No, save, check the message.", text="x", secrets=Secrets({"APP_PASSWORD": "s3cret!"})
)
PAGE = [
    Element(ref=1, tag="input", type="radio", label="Yes", checked=True),
    Element(ref=2, tag="input", type="radio", label="No", checked=False),
    Element(ref=3, tag="input", type="password", label="Password"),
    Element(ref=4, tag="button", text="Save"),
]


def entry(action: str, target: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"action": action, "step_no": 1, **fields}
    if target is not None:
        data["target"] = {"tag": "input", "role": "", "type": "", "kind": "", "text": "", "nth": 0, **target}
    return data


def replay(steps: list[dict[str, Any]], browser: FakeBrowser, tmp_path: Path, **options: Any) -> Any:
    options.setdefault("find_attempts", 2)
    options.setdefault("check_attempts", 2)
    options.setdefault("pause_s", 0)
    recording = {"recorded_at": "2026-10-12T10:00:00", "start_url": "http://app/", "steps": steps}
    return Replayer(recording, **options).run(SCENARIO, browser, tmp_path / "run")


def test_a_recording_replays_with_the_browser_helpers(tmp_path: Path) -> None:
    browser = FakeBrowser(text="Saved", elements=PAGE)
    result = replay(
        [
            entry("click", {"type": "radio", "label": "No", "checked": False}),
            entry("type", {"type": "password", "label": "Password"}, text="${APP_PASSWORD}", submit=False),
            entry("click", {"tag": "button", "text": "Save"}),
            entry("check", text="Saved", absent=False),
            entry("press", key="Escape"),
        ],
        browser,
        tmp_path,
    )
    assert result.success is True, result.reason
    assert result.model == REPLAY_MODEL
    assert result.usage is None
    assert result.reason == "Recording replayed without a model: 5 actions (recorded on 2026-10-12T10:00:00)."
    assert browser.calls[:3] == [("click", 2), ("type", 3, "s3cret!"), ("click", 4)]
    assert result.steps[1].result == 'Typed "${APP_PASSWORD}" into [3]', "the secret never reaches the report"
    assert result.steps[0].action["label"] == "No"
    assert result.steps[0].thought == "replay of the recording"
    assert {"step_01.png", "step_01_action.png", "final.png"} <= {p.name for p in (tmp_path / "run").iterdir()}


def test_data_changed_since_the_recording_is_never_modified_blindly(tmp_path: Path) -> None:
    # "No" was not ticked when recorded; it is now: the replay stops before clicking it.
    ticked = [*PAGE[:1], Element(ref=2, tag="input", type="radio", label="No", checked=True)]
    browser = FakeBrowser(elements=ticked)
    result = replay([entry("click", {"type": "radio", "label": "No", "checked": False})], browser, tmp_path)
    assert result.success is False
    assert browser.calls == []
    assert '"No" was unchecked when recorded and is checked now' in result.reason


def test_an_element_that_left_the_page_stops_the_replay(tmp_path: Path) -> None:
    browser = FakeBrowser(elements=PAGE)
    result = replay([entry("click", {"tag": "button", "text": "Export"})], browser, tmp_path)
    assert result.success is False
    assert result.reason.startswith("Replay stopped at action 1:")
    assert '"Export" is not on the page any more' in result.reason
    assert ("wait", 0) in browser.calls, "the page is given time to show the element"


def test_checks_are_retried_while_the_page_updates(tmp_path: Path) -> None:
    class Slow(FakeBrowser):
        def wait(self, seconds: float = 1.0) -> str:
            self.text = "Order created"
            return super().wait(seconds)

    result = replay([entry("check", text="Order created", absent=False)], Slow(text="Loading"), tmp_path)
    assert result.success is True
    assert result.steps[0].check is True


def test_a_failed_check_fails_the_replay(tmp_path: Path) -> None:
    result = replay([entry("check", text="Order created", absent=False), entry("back")], FakeBrowser(), tmp_path)
    assert result.success is False
    assert len(result.steps) == 1
    assert result.steps[0].check is False


def test_a_meaning_proof_is_looked_up_in_the_text_and_control_states(tmp_path: Path) -> None:
    # "the Save button is disabled" was proved by 'button "Save": disabled', which is not page text.
    proof = entry("check", meaning="the Save button is disabled", text='button "Save": disabled', absent=False)
    disabled = FakeBrowser(text='Add\n[Form controls]\nbutton "Save": disabled')
    assert replay([proof], disabled, tmp_path).success is True
    assert replay([proof], FakeBrowser(text="Add Save"), tmp_path).success is False


def test_unverifiable_checks_and_notes_do_not_fail_the_replay(tmp_path: Path) -> None:
    result = replay(
        [
            entry("check", meaning="no 2050 row", absent=True, replayable=False),
            entry("note", note="id = 28"),
            entry("check", url="/home", absent=False),
            entry("navigate", url="http://app/next"),
            entry("scroll", direction="up"),
            entry("wait", seconds=0),
            entry("back"),
            entry("select", {"tag": "select", "label": "Size"}, option="M"),
        ],
        FakeBrowser(url="http://app/home", elements=[Element(ref=5, tag="select", label="Size")]),
        tmp_path,
    )
    assert result.success is True, result.reason
    assert result.steps[0].result == "Not verifiable without a model (nothing precise to look for): no 2050 row"
    assert result.steps[0].check is None
    assert result.steps[1].result == "Note from the recording: id = 28"


def test_every_step_is_reported_to_the_listener(tmp_path: Path) -> None:
    seen: list[Step] = []

    class Listener:
        def on_plan(self, plan: object) -> None: ...

        def on_step(self, step: Step) -> None:
            seen.append(step)

    result = replay([entry("back")], FakeBrowser(), tmp_path, listener=Listener())
    assert seen == result.steps


def test_an_unknown_action_stops_the_replay(tmp_path: Path) -> None:
    result = replay([entry("teleport")], FakeBrowser(), tmp_path)
    assert result.success is False
    assert "Unknown action" in result.reason


def test_a_page_that_cannot_be_observed(tmp_path: Path) -> None:
    browser = FakeBrowser()
    browser.observe_error = RuntimeError("browser closed")
    result = replay([entry("back")], browser, tmp_path)
    assert result.reason == "Could not observe the page: browser closed"
