"""Interpreting a scenario written in business words into precise steps, and keeping the
interpretation honest: it may make the steps precise, never change what they expect."""

import pytest

from plainproof.agent.plan import clean_plan, plan_request_text
from plainproof.results import PlanStep


def test_request_text_numbers_the_lines_and_carries_the_context() -> None:
    text = plan_request_text(["I log in.", "I see the dashboard."], "Login: user field, password field.")
    assert "APPLICATION CONTEXT:\nLogin: user field, password field." in text
    assert "1. I log in.\n2. I see the dashboard." in text
    assert "APPLICATION CONTEXT:\n(none)" in plan_request_text(["x"], "")


class TestCleanPlan:
    @pytest.mark.parametrize(
        "answer",
        [
            {"steps": []},
            {"steps": [{"text": ""}]},
            [],
            {"nope": 1},
            {"steps": ["not an object"]},
            {"steps": [{"text": "x"}] * 81},
        ],
    )
    def test_unusable_answers(self, answer: object) -> None:
        assert clean_plan(answer, ["a line"]) is None

    def test_values_are_normalised(self) -> None:
        answer = {"steps": [{"text": "Click\nOK", "verify": "true", "source": 9}, {"text": "Go", "source": "x"}]}
        assert clean_plan(answer, ["a", "b"]) == [
            PlanStep("Click OK", verify=True, source=2),
            PlanStep("Go", source=0),
        ]

    def test_an_action_is_never_an_absence(self) -> None:
        plan = clean_plan({"steps": [{"text": "Delete", "verify": False, "absent": True, "source": 1}]}, ["x"])
        assert plan == [PlanStep("Delete", source=1)]

    def test_a_presence_is_never_turned_into_an_absence(self) -> None:
        # Seen in a real run: the context lists the real menus, the model reversed the expectation
        # of a test written to fail, and the test passed.
        lines = ["I open the app: at the top of the screen I see a Statistics menu."]
        answer = {
            "steps": [
                {"text": 'Verify that the menu has no "Statistics" entry', "verify": True, "absent": True, "source": 1}
            ]
        }
        assert clean_plan(answer, lines) == [PlanStep(lines[0], verify=True, source=1)]

    def test_a_named_value_dropped_by_the_model_is_verified_anyway(self) -> None:
        # "Users" was replaced by the real menu entry known from the context.
        lines = ["I open the app.", "When I click Administration, I can choose between Partners and Users."]
        unfaithful = {
            "steps": [
                {"text": 'Click "Administration"', "source": 2},
                {"text": 'Verify the menu shows "Partners" and "Reference policy"', "verify": True, "source": 2},
            ]
        }
        plan = clean_plan(unfaithful, lines)
        assert plan is not None
        assert plan[-1] == PlanStep(lines[1], verify=True, source=2)
        faithful = {
            "steps": [
                {"text": 'Click "Administration"', "source": 2},
                {"text": 'Verify the menu shows "Partners" and "Users"', "verify": True, "source": 2},
            ]
        }
        assert len(clean_plan(faithful, lines) or []) == 2

    def test_only_means_only_not_an_absence(self) -> None:
        # "il n'y a plus qu'une fiche : X" was split into "Y is shown" + "X is no longer shown".
        lines = ["Je filtre les brouillons.", "Il n'y a plus qu'une commande : \"Commande 42\"."]
        answer = {
            "steps": [
                {"text": 'Vérifier que "Commande 17" est affichée', "verify": True, "source": 2},
                {
                    "text": 'Vérifier que "Commande 42" n\'est plus affichée',
                    "verify": True,
                    "absent": True,
                    "source": 2,
                },
            ]
        }
        plan = clean_plan(answer, lines) or []
        assert PlanStep(lines[1], verify=True, source=2) in plan
        assert not any(s.absent for s in plan)

    @pytest.mark.parametrize(
        "line",
        [
            'The project "Shared garden" does not appear.',
            "The row is gone.",
            "No error message is shown.",
            "I cancel and accept to drop my input: the form closes.",
            'I delete "Partner after" and confirm: the deletion is confirmed.',
            "Plus aucune fiche n'est affichée.",
        ],
    )
    def test_a_real_absence_is_kept(self, line: str) -> None:
        answer = {"steps": [{"text": "Verify the absence", "verify": True, "absent": True, "source": 1}]}
        assert (clean_plan(answer, [line]) or [])[0].absent is True
