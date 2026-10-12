"""What the model reads about a page: numbered elements with their state."""

from plainproof.browser.model import CheckResult, Element, Observation


def el(ref: int, tag: str = "button", **fields: object) -> Element:
    return Element(ref=ref, tag=tag, **fields)  # type: ignore[arg-type]


class TestDescribe:
    def test_minimal(self) -> None:
        assert el(7, "input", type="text", label="Search").describe() == '[7] <input type="text"> label="Search"'

    def test_state_of_fields_checkboxes_and_menus(self) -> None:
        box = el(4, "input", type="checkbox", label="Monday / Morning", checked=False, kind="checkbox")
        assert box.describe() == '[4] <input type="checkbox"> label="Monday / Morning" unchecked'
        date = el(5, "input", role="combobox", label="Start date", value="01/03/2050", kind="date")
        assert 'value="01/03/2050"' in date.describe()
        assert "date field" in date.describe()
        menu = el(6, "a", text="Admin", expanded="false", href="#admin")
        assert menu.describe() == '[6] <a> text="Admin" expanded=false href=#admin'

    def test_select_options_and_position(self) -> None:
        select = el(8, "select", text="One", options=["One", "Two"], off="below", on_screen=False)
        assert select.describe() == (
            "[8] <select> text=\"One\" options=['One', 'Two'] "
            "(below the current view, it will be scrolled to automatically)"
        )

    def test_name(self) -> None:
        assert el(1, label="Save the form", text="Save").name == "Save the form"
        assert el(1, text="Save").name == "Save"


class TestObservation:
    def test_elements_text(self) -> None:
        obs = Observation(url="http://app/", title="App", elements=[el(1, text="OK"), el(2, text="Cancel")])
        assert obs.elements_text() == '[1] <button> text="OK"\n[2] <button> text="Cancel"'

    def test_empty_and_truncated_pages(self) -> None:
        assert Observation(url="u", title="t").elements_text() == "(no visible interactive element)"
        truncated = Observation(url="u", title="t", elements=[el(1, text="B1")], truncated=40)
        assert truncated.elements_text().endswith("(40 more elements further down the page: scroll to reach them)")

    def test_by_ref(self) -> None:
        obs = Observation(url="u", title="t", elements=[el(3, text="X")])
        assert obs.by_ref(3) is obs.elements[0]
        assert obs.by_ref(4) is None


def test_check_result() -> None:
    passed = CheckResult.passed('"Total" found')
    failed = CheckResult.failed('"Total" not found in page')
    assert passed.ok
    assert passed.message == 'CHECK OK: "Total" found'
    assert not failed.ok
    assert str(failed) == 'CHECK FAILED: "Total" not found in page'
