"""Language heuristics used by the verdict guards, whatever language the scenario is written in."""

import pytest

from plainproof.lexicon import asks_verification, says_absent


@pytest.mark.parametrize(
    "line",
    [
        "Check that the total is 42",
        "Verify the banner",
        "I should see the dashboard",
        "The list must contain Paris",
        "Make sure no error is shown",
        "Ensure the order is saved",
        "Assert the page title",
        "I expect a confirmation",
        "Confirm that the invoice is paid",
        "The page should display Welcome",
        "Then I see the dashboard",
        "Vérifie que la page contient Tableau de bord",
        "Je vois le tableau de bord",
        "Je dois voir le tableau",
        "La ligne ne doit plus apparaître",
        "On doit voir un message",
        "S'assurer que la commande est créée",
        "Contrôler le total",
    ],
)
def test_lines_that_ask_for_a_verification(line: str) -> None:
    assert asks_verification(line)


@pytest.mark.parametrize(
    "line",
    [
        "Click Save",
        "Confirm the deletion",  # a click on a confirmation button, not a check
        "Go to Settings",
        "Type hello in the search box",
        "Tick the checkbox",
        "Je confirme la suppression",
        "Dans les contrôles dynamiques, j'active le champ",
        "Clique sur Valider",
        "Je vais dans Commandes",
    ],
)
def test_actions_are_not_verifications(line: str) -> None:
    assert not asks_verification(line)


@pytest.mark.parametrize(
    "line",
    [
        "No error message is shown",
        "The row is gone",
        "The invoice no longer appears",
        "Nothing is displayed",
        "The list is empty",
        "It doesn't show the banner",
        "The item was removed",
        "The dialog closes without any warning",
        "Le projet n'apparaît pas",
        "La ligne a disparu",
        "Plus aucune fiche n'est affichée",
        "J'annule : le formulaire se ferme",
        "Je supprime la commande et je confirme",
    ],
)
def test_lines_that_express_an_absence(line: str) -> None:
    assert says_absent(line)


@pytest.mark.parametrize(
    "line",
    [
        "I see a Statistics menu",
        "The total is 42",
        "There is nothing but the header",  # "only", not an absence
        "The list shows no more than 3 rows",
        "Je vois un menu Statistiques",
        "Il n'y a plus qu'une commande : Commande 42",  # "ne ... que" means "only"
        "Il ne reste que deux lignes",
        "",
    ],
)
def test_affirmations_and_restrictions_are_not_absences(line: str) -> None:
    assert not says_absent(line)
