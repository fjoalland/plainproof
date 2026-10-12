"""Everything a human reads (reports, console, JUnit) follows the chosen language."""

import re

import pytest

from plainproof import i18n
from plainproof.i18n import (
    SUPPORTED,
    get_language,
    language_name,
    resolve_language,
    set_language,
    t,
    use_language,
)


def test_english_is_the_default() -> None:
    assert get_language() == "en"
    assert t("verdict.passed") == "PASSED"


def test_use_language_is_scoped() -> None:
    with use_language("fr"):
        assert get_language() == "fr"
        assert t("verdict.passed") == "RÉUSSI"
    assert get_language() == "en"


def test_set_language_accepts_locales_and_falls_back_to_english() -> None:
    try:
        assert set_language("fr-FR") == "fr"
        assert set_language("fr_CA") == "fr"
        assert set_language("klingon") == "en"
        assert set_language(None) == "en"
    finally:
        set_language("en")


def test_placeholders_are_filled() -> None:
    assert t("reason.max_steps", n=25) == "Maximum number of actions reached (25) without a verdict."


def test_unknown_key_is_returned_as_is() -> None:
    assert t("no.such.key") == "no.such.key"


@pytest.mark.parametrize(
    ("explicit", "env", "locale", "expected"),
    [
        ("fr", "en", "en-US", "fr"),  # --language wins
        (None, "fr", "en-US", "fr"),  # then $PLAINPROOF_LANGUAGE
        (None, None, "fr-FR", "fr"),  # then the browser locale
        (None, None, None, "en"),
        ("xx", None, "fr-FR", "fr"),  # an unsupported value is skipped
    ],
)
def test_resolve_language(explicit: str | None, env: str | None, locale: str | None, expected: str) -> None:
    assert resolve_language(explicit, env, locale) == expected


def test_language_name_is_given_to_the_model_in_english() -> None:
    assert language_name("fr") == "French"
    assert language_name("en") == "English"


def test_every_catalog_has_the_same_keys_and_placeholders() -> None:
    english = i18n.catalog("en")
    for code in SUPPORTED:
        other = i18n.catalog(code)
        assert set(other) == set(english), f"{code}: keys differ from English"
        for key, text in english.items():
            fields = set(re.findall(r"{(\w+)", text))
            assert set(re.findall(r"{(\w+)", other[key])) == fields, f"{code}: placeholders of {key}"
