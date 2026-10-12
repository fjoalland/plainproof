"""Verifications judged on meaning: the judge may read the page, it may not imagine it.

A positive verdict only counts when the passage quoted by the judge really is on the page,
says something, was not typed there by the agent itself, and keeps every exact wording the
expectation names.
"""

from typing import Any

from plainproof.agent.judge import evaluate_judgement, judge_request_text


def judge(answer: dict[str, Any], expectation: str, page: str, absent: bool = False, typed: str = "") -> Any:
    return evaluate_judgement(answer, expectation, absent, page, lambda quote: bool(typed) and quote == typed)


def yes(evidence: str) -> dict[str, Any]:
    return {"satisfied": True, "evidence": evidence, "explanation": "seen"}


def test_passes_when_the_quote_is_on_the_page() -> None:
    page = "Search\nPlease fill in at least one filter.\nRun the search"
    outcome = judge(yes("Please fill in at least one filter"), "a message says a filter is required", page)
    assert outcome.check is True
    assert outcome.by_meaning
    assert outcome.message == (
        'CHECK OK (by meaning): "a message says a filter is required". '
        'The page shows: "Please fill in at least one filter"'
    )
    assert outcome.evidence == "Please fill in at least one filter"


def test_a_quote_the_page_does_not_contain_is_refused() -> None:
    page = "An error occurred while creating the campaign"
    outcome = judge(yes("The end date must be after the start date"), "a message about inconsistent dates", page)
    assert outcome.check is False
    assert "could not quote the page" in outcome.message


def test_quote_marks_and_spacing_do_not_matter() -> None:
    page = "Error: the agent can't be delegated."
    assert judge(yes("the agent  can’t be delegated"), "refused", page).check is True


def test_a_quote_too_short_to_prove_anything_is_refused() -> None:
    # "on" is on every page: it once "proved" that a box was ticked.
    assert judge(yes("on"), 'The box "checkbox 1" is ticked', "checkbox 1 checkbox 2 on on").check is False


def test_another_wording_than_the_quoted_one_is_refused() -> None:
    # The judge accepted, on a retry, the real message, different from the expected one.
    page = "Deletion\nDo you want to delete this project?\nYes No"
    expected = 'Verify that the message "Are you sure you want to erase this project?" is shown'
    outcome = judge(yes("Do you want to delete this project?"), expected, page)
    assert outcome.check is False
    assert "cannot be replaced by another one" in outcome.message
    same = 'Verify that "Do you want to delete this project?" is shown'
    assert judge(yes("Do you want to delete this project?"), same, page).check is True


def test_a_named_label_missing_from_the_page_is_refused() -> None:
    # "Partners and Users" accepted on the strength of "Administration Partners" alone.
    page = "Projects Administration Partners Reference policy Map"
    expected = "When I click Administration, I can choose between Partners and Users."
    assert judge(yes("Administration Partners"), expected, page).check is False
    # a negative sentence may name what must not be there
    negative = "I find Projects and Administration, but no Statistics menu."
    assert judge(yes("Projects Administration Partners"), negative, page).check is True


def test_a_quote_found_only_in_a_field_the_agent_typed_is_refused() -> None:
    page = "Filter: Globex\nNo result"
    outcome = judge(yes("Globex"), "the customer Globex is listed", page, typed="Globex")
    assert outcome.check is False
    assert "typed it into yourself" in outcome.message


def test_an_absence_needs_no_quote() -> None:
    outcome = judge(
        {"satisfied": True, "evidence": "", "explanation": "no 2050 row"},
        "the order is gone",
        "Orders\n14 07/07/2026",
        absent=True,
    )
    assert outcome.check is True
    assert outcome.message == 'CHECK OK (by meaning): "the order is gone". no 2050 row'


def test_a_negative_verdict_keeps_the_explanation() -> None:
    outcome = judge({"satisfied": "false", "explanation": "only a generic error"}, "a message about dates", "x")
    assert outcome.check is False
    assert outcome.message == 'CHECK FAILED (by meaning): "a message about dates". only a generic error'


def test_request_text() -> None:
    text = judge_request_text("the order is gone", True, "http://app/orders", "PAGE BODY " * 3000)
    assert text.startswith("EXPECTED RESULT (must NOT be shown): the order is gone\n\nCURRENT PAGE: http://app/orders")
    assert len(text) < 16000, "the page text is capped"
