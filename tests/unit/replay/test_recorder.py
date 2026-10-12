"""Recording the actions of a passing run, in a form that can be replayed without a model."""

import json

from plainproof.agent.actions import Outcome
from plainproof.browser.model import Element, Observation
from plainproof.replay.recorder import Recorder
from plainproof.secrets import Secrets


def el(ref: int, text: str = "", label: str = "", tag: str = "button", type_: str = "") -> Element:
    return Element(ref=ref, tag=tag, text=text, label=label, type=type_)


PAGE = Observation(
    url="http://app/login",
    title="Login",
    elements=[
        el(1, label="Password", tag="input", type_="password"),
        el(2, "Log in"),
    ],
)


def test_actions_are_recorded_with_a_stable_target_and_placeholders() -> None:
    recorder = Recorder(Secrets({"APP_PASSWORD": "s3cret!"}))
    recorder.start("http://app/login")
    recorder.start("http://app/elsewhere")  # only the first page counts
    recorder.add({"action": "type", "ref": 1, "text": "${APP_PASSWORD}"}, PAGE, Outcome('Typed "x" into [1]'), 1)
    recorder.add({"action": "type", "ref": 1, "text": "s3cret!"}, PAGE, Outcome('Typed "join [2]" into [1]'), 1)
    # the model said [9], the browser redirected by label to [2]: the recording follows [2]
    recorder.add({"action": "click", "ref": 9, "label": "Log in"}, PAGE, Outcome('Clicked [2] "Log in"'), 2)
    data = recorder.data("01-login", "anthropic:claude-sonnet-5-5")
    assert data["version"] == 1
    assert data["scenario"] == "01-login"
    assert data["start_url"] == "http://app/login"
    assert [s["text"] for s in data["steps"][:2]] == ["${APP_PASSWORD}", "${APP_PASSWORD}"]
    assert data["steps"][1]["target"]["label"] == "Password", "a [n] inside the typed text is not the target"
    assert data["steps"][2]["target"]["text"] == "Log in"
    assert data["steps"][2]["step_no"] == 2
    assert "s3cret!" not in json.dumps(data)


def test_checks_are_recorded_as_what_to_look_for() -> None:
    recorder = Recorder()
    nothing = Observation(url="u", title="t")
    recorder.add(
        {"action": "check", "meaning": "a confirmation"},
        nothing,
        Outcome("CHECK OK (by meaning)", check=True, evidence="Order created successfully", by_meaning=True),
    )
    recorder.add(
        {"action": "check", "meaning": "no 2050 row", "absent": True},
        nothing,
        Outcome("CHECK OK (by meaning)", check=True, by_meaning=True),
    )
    recorder.add({"action": "check", "url": "/orders"}, nothing, Outcome("CHECK OK", check=True))
    recorder.add({"action": "check", "text": "Total"}, nothing, Outcome("CHECK OK", check=True))
    recorder.add({"action": "check", "text": "Absent"}, nothing, Outcome("CHECK FAILED", check=False))
    steps = recorder.data("x", "m")["steps"]
    assert steps[0] == {
        "action": "check",
        "step_no": 0,
        "absent": False,
        "meaning": "a confirmation",
        "text": "Order created successfully",
    }
    assert steps[1]["replayable"] is False, "an absence judged on meaning has nothing precise to look for"
    assert steps[2]["url"] == "/orders"
    assert steps[3]["text"] == "Total"
    assert len(steps) == 4, "a failed check is not replayed"


def test_other_actions_keep_their_parameters() -> None:
    recorder = Recorder()
    page = Observation(url="u", title="t", elements=[el(4, label="Plan", tag="select")])
    for action, message in [
        ({"action": "select", "ref": 4, "option": "Monthly"}, 'Selected "Monthly" in [4]'),
        ({"action": "press", "key": "Escape"}, "Pressed Escape"),
        ({"action": "scroll", "direction": "up"}, "Scrolled up"),
        ({"action": "wait", "seconds": 2}, "Waited 2s"),
        ({"action": "navigate", "url": "https://x.test"}, "Navigated"),
        ({"action": "note", "note": "id = 28"}, "Note recorded"),
        ({"action": "back"}, "Went back"),
        ({"action": "finish", "success": True}, "Test finished"),
        ({"action": "click", "ref": 99}, "Clicked [99]"),  # an element the observation does not know
    ]:
        recorder.add(action, page, Outcome(message), 1)
    steps = recorder.data("x", "m")["steps"]
    assert [s["action"] for s in steps] == ["select", "press", "scroll", "wait", "navigate", "note", "back"]
    assert steps[0]["option"] == "Monthly"
    assert steps[0]["target"]["label"] == "Plan"
    assert steps[1]["key"] == "Escape"
    assert steps[2]["direction"] == "up"
    assert steps[3]["seconds"] == 2.0
    assert steps[4]["url"] == "https://x.test"
    assert steps[5]["note"] == "id = 28"
