"""Reading the actions the model decides."""

import pytest

from plainproof.agent.actions import as_ref, banner, check_fragment, check_key, short_params


@pytest.mark.parametrize(("value", "expected"), [(3, 3), ("12", 12), (4.0, 4), (None, None), ("x", None), (True, None)])
def test_as_ref(value: object, expected: int | None) -> None:
    assert as_ref(value) == expected


def test_check_key_identifies_a_check_and_its_polarity() -> None:
    assert check_key({"action": "check", "text": "Error", "absent": "true"}) == ("Error", True)
    assert check_key({"action": "check", "url": "/orders"}) == ("/orders", False)
    assert check_key({"action": "check", "meaning": "a success message"}) == ("a success message", False)
    assert check_key({"action": "click", "ref": 1}) is None


def test_check_fragment() -> None:
    assert check_fragment({"action": "check", "url": "/a", "text": "b"}) == "/a"
    assert check_fragment({"action": "check"}) == ""


def test_short_params_hide_the_reasoning() -> None:
    action = {"action": "type", "thought": "...", "step": 2, "note": "x", "ref": 5, "text": "hello"}
    assert short_params(action) == "ref=5 text='hello'"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ({"action": "click", "ref": 3}, "CLICK [3]"),
        ({"action": "type", "ref": 2, "text": "Ada", "submit": True}, 'TYPE [2] "Ada"  + Enter'),
        ({"action": "select", "ref": 6, "option": "Two"}, 'SELECT [6] "Two"'),
        ({"action": "navigate", "url": "https://x.test"}, "NAVIGATE https://x.test"),
        ({"action": "check", "text": "330 m"}, "CHECK '330 m'"),
        ({"action": "finish", "success": True}, "FINISH PASS"),
        ({"action": "finish", "success": "false"}, "FINISH FAIL"),
        ({"action": "press", "key": "Enter"}, "PRESS key='Enter'"),
    ],
)
def test_banner(action: dict[str, object], expected: str) -> None:
    assert banner(action) == expected
