"""Finding the element the model meant: by number, confirmed by its label."""

import pytest

from plainproof.browser.matching import TargetError, match_option, resolve_target
from plainproof.browser.model import Element


def el(ref: int, text: str = "", label: str = "", tag: str = "button") -> Element:
    return Element(ref=ref, tag=tag, text=text, label=label)


PAGE = {
    e.ref: e
    for e in [
        el(1, "Create invoice"),
        el(2, "Add Jane DOE to the recipients"),
        el(3, label="Search a customer, an invoice", tag="input"),
        el(4, "Delete"),
        el(5, "Delete"),
        el(6, "Validate"),
    ]
}


class TestResolveTarget:
    def test_number_confirmed_by_its_label(self) -> None:
        assert resolve_target(PAGE, 1, "Create invoice") == (1, "")

    def test_no_label_trusts_the_number(self) -> None:
        assert resolve_target(PAGE, 6, None) == (6, "")

    def test_a_stale_number_is_corrected_to_the_element_carrying_that_exact_name(self) -> None:
        # Numbers are recomputed at every observation: reusing the previous turn's number once
        # clicked "Add ... to the recipients" instead of "Create invoice".
        ref, note = resolve_target(PAGE, 2, "Create invoice")
        assert ref == 1
        assert "used that one" in note

    def test_a_label_without_number_is_found(self) -> None:
        ref, note = resolve_target(PAGE, None, "create INVOICE")
        assert ref == 1
        assert "no number was given" in note

    def test_a_partial_name_is_not_redirected_to_a_longer_label(self) -> None:
        # Aiming at the button "Search" must not type into the field "Search a customer...".
        with pytest.raises(TargetError, match="Search a customer") as err:
            resolve_target(PAGE, 6, "Search")
        assert err.value.kind == "mismatch"

    def test_an_ambiguous_label_lists_the_candidates(self) -> None:
        with pytest.raises(TargetError, match=r"\[4\] \"Delete\", \[5\] \"Delete\"") as err:
            resolve_target(PAGE, 6, "Delete")
        assert err.value.kind == "mismatch"

    def test_a_label_absent_from_the_page(self) -> None:
        with pytest.raises(TargetError, match="no element on this page carries that label") as err:
            resolve_target(PAGE, 6, "Export to PDF")
        assert err.value.kind == "missing"
        assert err.value.wanted == "export to pdf"

    def test_a_number_absent_from_the_page(self) -> None:
        with pytest.raises(TargetError, match=r"\[99\] is not on the page"):
            resolve_target(PAGE, 99, "Export to PDF")

    def test_neither_number_nor_label(self) -> None:
        with pytest.raises(TargetError, match="No element number given"):
            resolve_target(PAGE, None, None)


class TestMatchOption:
    options = ("Monthly plan", "Weekly", "Préférences")

    def test_exact_ignoring_case_and_accents(self) -> None:
        assert match_option(self.options, "preferences") == 2

    def test_prefix_then_substring(self) -> None:
        assert match_option(self.options, "Monthly") == 0
        assert match_option(self.options, "plan") == 0

    def test_no_match(self) -> None:
        assert match_option(self.options, "Yearly") is None
        assert match_option(self.options, "") is None
