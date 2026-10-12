"""Shared fixtures."""

from collections.abc import Iterator

import pytest

from plainproof.i18n import set_language


@pytest.fixture(autouse=True)
def _english_by_default() -> Iterator[None]:
    """Every test starts in English, whatever the previous one selected."""
    set_language("en")
    yield
    set_language("en")
