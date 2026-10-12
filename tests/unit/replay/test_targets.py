"""Describing an element so that it can be found again on another day, without its number."""

from plainproof.browser.model import Element
from plainproof.replay.targets import find_target, same_row, target_name, target_of


def el(ref: int, text: str = "", label: str = "", tag: str = "button", checked: bool | None = None) -> Element:
    return Element(ref=ref, tag=tag, text=text, label=label, checked=checked)


def test_rank_among_identical_elements() -> None:
    elements = [el(1, "Delete"), el(2, "Edit"), el(3, "Delete")]
    target = target_of(elements[2], elements)
    assert target["nth"] == 1  # the second "Delete" of the page, whatever its number
    assert find_target(target, [el(7, "Delete"), el(8, "Delete"), el(9, "Edit")]) == el(8, "Delete")


def test_the_state_of_a_checkbox_is_kept() -> None:
    box = el(1, label="Newsletter", tag="input", checked=False)
    assert target_of(box, [box])["checked"] is False
    assert "checked" not in target_of(el(2, "Save"), [el(2, "Save")])


def test_the_row_decides_when_the_identifier_changed() -> None:
    # recorded: the bin of order 61; replayed after the order was created again as 63
    recorded = [el(5, "Delete order 23"), el(6, "Delete order 61")]
    rows = {"5": "23 Acme 01/12/2025 10/01/2026", "6": "61 Acme 01/12/2050 10/01/2051"}
    target = target_of(recorded[1], recorded, rows)
    assert target["row"] == rows["6"]
    now = [el(8, "Delete order 23"), el(9, "Delete order 63")]
    now_rows = {"8": "23 Acme 01/12/2025 10/01/2026", "9": "63 Acme 01/12/2050 10/01/2051"}
    assert find_target(target, now, now_rows) == now[1]


def test_the_row_wins_over_the_rank() -> None:
    recorded = [el(1, "Delete"), el(2, "Delete")]
    target = target_of(recorded[1], recorded, {"1": "Running 40 h 01/03/2025", "2": "Planned 36 h 01/01/2050"})
    swapped = {"1": "Planned 36 h 01/01/2050", "2": "Running 40 h 01/03/2025"}
    assert find_target(target, recorded, swapped) == recorded[0]


def test_an_ambiguous_or_missing_row_finds_nothing() -> None:
    target = target_of(el(1, "Delete"), [el(1, "Delete")], {"1": "36 h 01/01/2050"})
    two = [el(1, "Delete"), el(2, "Delete")]
    assert find_target(target, two, {"1": "36 h 01/01/2050", "2": "36 h 01/01/2050"}) is None  # which one?
    assert find_target(target, two, {"1": "40 h 01/03/2025", "2": "39 h 01/06/2025"}) is None  # gone


def test_an_element_no_longer_on_the_page() -> None:
    target = target_of(el(1, "Validate"), [el(1, "Validate")])
    assert find_target(target, [el(1, "Cancel")]) is None


def test_same_row() -> None:
    # cells that come back in another order are the same row
    recorded = "NORTH Sport for seniors Healthy ageing Solidarity between generations Running 12-2049"
    current = "NORTH Sport for seniors Solidarity between generations Healthy ageing Running 12-2049"
    assert same_row(recorded, current)
    assert not same_row(recorded, "SOUTH Car sharing Mobility Finished 12-2019")
    # every date of the recorded row must be there
    assert not same_row("Order 01/12/2050", "Order 02/12/2050")


def test_target_name() -> None:
    assert target_name({"label": "Save the form", "text": "Save"}) == "Save the form"
    assert target_name({"text": " Save "}) == "Save"
    assert target_name({}) == ""
