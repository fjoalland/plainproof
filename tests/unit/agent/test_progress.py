"""What the model is reminded of at every turn: the step it reached, its notes, its history.

Everything else of its reasoning is dropped between turns: without this, agents used to
restart a scenario from the middle or skip the second half of "click X and verify Y".
"""

from plainproof.agent.progress import history_text, numbered, progress_text

from .helpers import step

LINES = ["Log in.", "Click Billing and verify that the page shows Invoices.", "Click Export."]


def test_numbered() -> None:
    assert numbered(LINES).startswith("1. Log in.\n2. Click Billing")


def test_before_the_first_action() -> None:
    assert progress_text(LINES, 0, [], []) == "No step done yet. Start with step 1 of 3: Log in."


def test_the_current_step_is_not_called_done() -> None:
    history = [step(1, {"action": "click", "ref": 1}, step_no=1), step(2, {"action": "click", "ref": 2}, step_no=2)]
    text = progress_text(LINES, 2, history, [], source_line="I go to billing and I see the invoices")
    assert "Steps 1 to 1 of 3 are done: NEVER redo them." in text
    assert "CURRENT STEP 2 of 3: Click Billing and verify that the page shows Invoices." in text
    assert 'written by the scenario author as: "I go to billing and I see the invoices"' in text
    assert "Actions already made for step 2: click ref=2" in text
    assert "NEXT STEP 3: Click Export." in text


def test_failed_actions_are_flagged_and_the_last_step_says_finish() -> None:
    history = [
        step(1, {"action": "check", "text": "Total"}, check=False, step_no=3),
        step(2, {"action": "click", "ref": 9}, error="missing", step_no=3),
    ]
    text = progress_text(LINES, 3, history, [])
    assert "check text='Total' (CHECK FAILED); click ref=9 (ERROR)" in text
    assert "This is the last step" in text


def test_notes_are_given_back() -> None:
    assert "  - customer = Jane DOE" in progress_text(LINES, 1, [], ["customer = Jane DOE"])


def test_history_text() -> None:
    history = [
        step(
            1,
            {"action": "click", "ref": 3, "thought": "go"},
            result='Clicked [3] "Billing"',
            step_no=1,
            url="http://app/",
            url_after="http://app/billing",
        ),
        step(2, {"action": "click", "ref": 9}, error="[9] does not exist", url="http://app/billing"),
    ]
    assert history_text(history) == (
        '1. [step 1] click ref=3 -> Clicked [3] "Billing"  -> page: http://app/billing\n'
        "2. click ref=9 -> ERROR: [9] does not exist"
    )
    assert history_text([]) == "(no action yet)"
