"""Deterministic guards between the model and the verdict.

Each guard answers a failure, or a false success, observed on real applications: the model
cannot declare success over a failed check, skip a verification, rephrase an expectation
until it passes, or spin on a step until the budget runs out.
"""

from plainproof.agent.guards import (
    already_succeeded,
    bind_check,
    failed_checks_tail,
    needs_check,
    realign_step,
    repeated_tail,
    scroll_tail,
    stalled_on_step,
    sterile_tail,
    unverified_steps,
    verdict_objection,
)
from plainproof.results import PlanStep

from .helpers import check, step


# -- loop detectors -----------------------------------------------------------------------
def test_scroll_tail() -> None:
    scrolls = [step(i, {"action": "scroll", "direction": "down"}) for i in range(3)]
    assert scroll_tail(scrolls) == 3
    assert scroll_tail([*scrolls, step(4)]) == 0


def test_failed_checks_tail() -> None:
    assert failed_checks_tail([check("a", True), check("b", False), check("c", False)]) == 2


def test_repeated_tail_counts_the_same_action_with_the_same_outcome() -> None:
    same = [step(i, {"action": "check", "text": "x", "thought": str(i)}, result="CHECK FAILED") for i in range(3)]
    assert repeated_tail(same) == 3
    assert repeated_tail([]) == 0


def test_a_toggle_alternating_open_and_closed_is_not_a_repetition() -> None:
    toggles = [step(i, {"action": "click", "ref": 1}, result="open" if i % 2 else "closed") for i in range(6)]
    assert repeated_tail(toggles) == 1


def test_sterile_tail() -> None:
    idle = [step(i, {"action": "scroll", "direction": "up" if i % 2 else "down"}) for i in range(8)]
    assert sterile_tail(idle)
    assert not sterile_tail([*idle[:-1], step(9, {"action": "click", "ref": 3})]), "a click may change things"
    moved = [*idle[:-1], step(9, {"action": "scroll", "direction": "up"}, url_after="http://app/#/other")]
    assert not sterile_tail(moved), "a page change is progress"
    assert not sterile_tail(idle[:5]), "too short to judge"


def test_stalled_on_step() -> None:
    stuck = [step(i, {"action": "click", "ref": i}, step_no=2) for i in range(12)]
    assert stalled_on_step(stuck, total=5)
    assert not stalled_on_step(stuck, total=2), "on the last step, let it conclude"
    assert not stalled_on_step(stuck[:11], total=5)
    assert not stalled_on_step([*stuck[:11], step(12, step_no=3)], total=5)


# -- redundant actions ----------------------------------------------------------------------
def test_a_successful_check_or_typing_is_not_repeated() -> None:
    done = [check("Invoices", True, step_no=2)]
    assert already_succeeded({"action": "check", "text": "Invoices", "label": "x", "thought": "t"}, done, 2) is done[0]
    assert already_succeeded({"action": "check", "text": "Invoices"}, done, 3) is None, "another step"
    assert already_succeeded({"action": "check", "text": "Invoices", "absent": True}, done, 2) is None


def test_a_failed_check_or_a_click_is_never_redundant() -> None:
    failed = [check("Invoices", False, step_no=2)]
    assert already_succeeded({"action": "check", "text": "Invoices"}, failed, 2) is None
    clicked = [step(1, {"action": "click", "ref": 1}, result="Clicked", step_no=1)]
    assert already_succeeded({"action": "click", "ref": 1}, clicked, 1) is None, "a menu may need a second click"


def test_a_typing_whose_field_warned_is_not_redundant() -> None:
    warned = [step(1, {"action": "type", "ref": 1, "text": "x"}, result="(WARNING: the field is empty)", step_no=1)]
    assert already_succeeded({"action": "type", "ref": 1, "text": "x"}, warned, 1) is None


# -- what must be verified ----------------------------------------------------------------
LINES = ["Log in.", "Click Billing and verify that the page shows Invoices.", "Click Export."]


def test_needs_check_from_the_plan_or_from_the_wording() -> None:
    assert needs_check(LINES, None, 2)
    assert not needs_check(LINES, None, 1)
    assert needs_check(LINES, [False, False, True], 3)
    assert not needs_check(LINES, [False, False, True], 2)


def test_unverified_steps() -> None:
    clicks = [step(1, step_no=1), step(2, step_no=2), step(3, step_no=3)]
    assert unverified_steps(LINES, clicks, None) == [2]
    assert unverified_steps(LINES, [*clicks, check("Invoices", True, step_no=2)], None) == []
    # with a plan, only a check that PROVES its step counts
    flags = [False, True, False]
    assert unverified_steps(LINES, [*clicks, check("x", True, step_no=2, proof=False)], flags) == [2]
    assert unverified_steps(LINES, [*clicks, check("x", True, step_no=2, proof=True)], flags) == []


class TestVerdictObjection:
    def test_the_last_check_failed(self) -> None:
        steps = [check("a", True, step_no=1), check("b", False, step_no=1)]
        assert "last check FAILED" in (verdict_objection(["Verify b"], steps, None) or "")
        assert verdict_objection(["Verify a"], list(reversed(steps)), None) is None

    def test_a_verification_was_asked_but_none_was_made(self) -> None:
        assert "no check was made" in (verdict_objection(["Click Save, then verify the message"], [], None) or "")
        assert verdict_objection(["Click Save and finish"], [], None) is None

    def test_the_scenario_was_not_finished(self) -> None:
        objection = verdict_objection(LINES, [step(1, step_no=1), check("Invoices", True, step_no=2)], None)
        assert objection == "Success verdict refused: the agent only reached step 2 of 3 of the scenario."

    def test_a_verification_step_was_skipped(self) -> None:
        steps = [check("x", True, step_no=1), step(2, step_no=2), step(3, step_no=3)]
        assert "step(s) 2" in (verdict_objection(LINES, steps, None) or "")

    def test_a_weaker_check_after_a_failed_proof_does_not_count(self) -> None:
        # The expected message failed, then "an error is shown" passed: a failure.
        flags = [False, True]
        lines = ["Click Create.", "A message says that the end date must be after the start date."]
        steps = [step(1, step_no=1), check("end date", False, step_no=2, proof=True), check("error", True, step_no=2)]
        assert verdict_objection(lines, steps, flags) == 'Success verdict refused: the last check FAILED ("end date").'

    def test_each_exact_value_of_a_step_stands_on_its_own(self) -> None:
        # The expected message failed every check, then the dialog title (another value of the
        # same step) was found and passed for the whole step.
        lines = ['A dialog "Deletion" asks "Do you really want to delete this order?"']
        steps = [
            check("Do you really want to delete this order?", False, step_no=1, proof=True),
            check("Deletion", True, step_no=1, proof=True),
        ]
        objection = verdict_objection(lines, steps, [True])
        assert objection is not None
        assert "Do you really want to delete this order?" in objection


# -- binding a check to its verification step ------------------------------------------------
SPEC = PlanStep('The message "Order saved" is shown for order 2050-001', verify=True)


def test_a_meaning_check_always_judges_the_step_wording() -> None:
    action, proves, note = bind_check({"action": "check", "meaning": "an error is shown"}, SPEC, 3)
    assert proves
    assert note == ""
    assert action["meaning"] == SPEC.text
    assert action["absent"] is False


def test_a_text_check_on_an_exact_value_proves_the_step() -> None:
    _, proves, _ = bind_check({"action": "check", "text": "Order saved"}, SPEC, 3)
    assert proves


def test_the_polarity_comes_from_the_plan() -> None:
    gone = PlanStep("The order 2050-001 no longer appears", verify=True, absent=True)
    action, proves, _ = bind_check({"action": "check", "text": "2050-001"}, gone, 2)
    assert proves
    assert action["absent"] is True


def test_a_long_passage_of_the_expectation_proves_it_a_short_one_does_not() -> None:
    spec = PlanStep("A message says that the request type is required", verify=True)
    assert bind_check({"action": "check", "text": "The request type is required"}, spec, 1)[1]
    action, proves, note = bind_check({"action": "check", "text": "request type"}, spec, 1)
    assert not proves
    assert '"meaning" check' in note
    assert action == {"action": "check", "text": "request type"}


def test_the_hint_names_the_exact_values_to_look_for() -> None:
    _, proves, note = bind_check({"action": "check", "text": "saved"}, SPEC, 3)
    assert not proves
    assert '"Order saved"' in note
    assert "step 3" in note


# -- step numbers lagging one behind ------------------------------------------------------------
PLAN = [
    PlanStep('Click the radio button "Yes"', source=1),
    PlanStep('Click "Create the subscription"', source=1),
    PlanStep("The application refuses: this status already has one", verify=True, source=2),
]


def test_an_action_on_the_next_step_target_counts_for_that_step() -> None:
    # "Create the subscription" clicked with the radio step's number: the agent then believed
    # the click was still to do and clicked it four times.
    action = {"action": "click", "ref": 2, "label": "Create the subscription"}
    assert realign_step(action, 1, PLAN, []) == 2


def test_no_realignment_when_the_target_belongs_to_the_current_step() -> None:
    plan = [PlanStep('Click the field "Reason"'), PlanStep('Click the first option of the list "Reason"')]
    assert realign_step({"action": "click", "ref": 1, "label": "Reason"}, 1, plan, []) == 1


def test_a_check_right_after_an_action_step_counts_for_the_verification_that_follows() -> None:
    plan = [PlanStep('Click "Delete"'), PlanStep("The order is no longer listed", verify=True, absent=True)]
    history = [step(1, {"action": "click", "ref": 3, "label": "Delete"}, step_no=1)]
    assert realign_step({"action": "check", "text": "x"}, 1, plan, history) == 2
    assert realign_step({"action": "check", "text": "x"}, 1, plan, []) == 1, "nothing done yet for step 1"
    assert realign_step({"action": "check", "text": "x"}, 2, plan, history) == 2, "already on the last step"
