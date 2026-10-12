"""Text helpers: every comparison between what a scenario says and what a page shows goes through them."""

import pytest

from plainproof.text import anchor_hit, anchors, labels, named_values, normalize, squash, truthy


class TestNormalize:
    def test_ignores_case_accents_and_spacing(self) -> None:
        assert normalize("  Café   Crème\tÉTÉ ") == "cafe creme ete"

    def test_repairs_utf8_read_as_latin1(self) -> None:
        # A misconfigured server sends "é" as "Ã©": a check for "Saved successfully" in French must still match.
        assert normalize("EnregistrÃ© avec succÃ¨s") == normalize("Enregistré avec succès")

    def test_leaves_a_lone_suspicious_character_alone(self) -> None:
        assert normalize("© 2026 Ã") == "© 2026 a"

    def test_empty(self) -> None:
        assert normalize("") == ""


def test_squash_keeps_letters_and_digits_only() -> None:
    assert squash("L’invoice  “INV-2050” is paid!") == "linvoiceinv2050ispaid"
    assert squash("") == ""


@pytest.mark.parametrize("value", [True, "true", " TRUE ", "1", "yes", "Yes", "oui", 1])
def test_truthy(value: object) -> None:
    assert truthy(value) is True


@pytest.mark.parametrize("value", [False, None, "false", "no", "0", "", 0, "maybe"])
def test_falsy(value: object) -> None:
    assert truthy(value) is False


class TestAnchors:
    def test_quoted_wording_in_any_quote_style(self) -> None:
        text = 'The page shows "Order saved", «Commande enregistrée» or “Saved”'
        assert anchors(text) == ["Order saved", "Commande enregistrée", "Saved"]

    def test_dates_numbers_and_identifiers(self) -> None:
        assert anchors("The booking of 01/03/2050 for customer 012345A, room 34") == ["01/03/2050", "012345A", "34"]

    def test_iso_dates_stay_whole(self) -> None:
        assert anchors("Delivery on 2050-03-01") == ["2050-03-01"]

    def test_placeholders(self) -> None:
        assert anchors("Type ${APP_USER} in the login field") == ["${APP_USER}"]

    def test_a_loose_description_names_nothing_exact(self) -> None:
        assert anchors("A message explains that the end date must be after the start date") == []

    def test_single_digits_are_not_identifiers(self) -> None:
        assert anchors("Click the 2nd row") == []


class TestNamedValues:
    def test_capitalised_labels_inside_a_sentence(self) -> None:
        assert named_values("When I open Administration, I can choose Partners or Users.") == [
            "Administration",
            "Partners",
            "Users",
        ]

    def test_sentence_starts_and_english_pronouns_are_not_labels(self) -> None:
        assert named_values("I'm on the home page. Then I'll click Save. It works.") == ["Save"]

    def test_french_labels(self) -> None:
        assert named_values("je peux choisir entre Fournisseurs et Utilisateurs") == ["Fournisseurs", "Utilisateurs"]

    def test_include_the_anchors(self) -> None:
        assert named_values('I see "Order saved" in Orders') == ["Order saved", "Orders"]

    def test_labels_alone(self) -> None:
        assert labels('I see "Order saved" in Orders on 01/02/2050') == ["Orders"]


def test_anchor_hit() -> None:
    step = 'Click "Create invoice" for customer 012345A'
    assert anchor_hit(step, squash("Create invoice"))
    assert anchor_hit(step, squash("customer 012345A"))
    assert not anchor_hit(step, squash("Delete"))
    assert not anchor_hit("Click Save", squash("Save"))  # nothing exact in the step
