"""Language of everything a human reads: reports, console, JUnit, verdicts and explanations.

Prompts stay in English (models follow them best that way); the model is told which
language to use for what it writes for humans (its reasoning, verdicts, explanations).

Catalogs are JSON files next to this module, one per language. To add a language, copy
``en.json``, translate the values (keep the ``{placeholders}``), and add its code to
:data:`SUPPORTED` and :data:`LANGUAGE_NAMES`. A test checks that every catalog has the same
keys and placeholders as the English one.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from importlib import resources

SUPPORTED: tuple[str, ...] = ("en", "fr")
DEFAULT = "en"
LANGUAGE_NAMES = {"en": "English", "fr": "French"}

_current: ContextVar[str] = ContextVar("plainproof_language", default=DEFAULT)


@functools.cache
def catalog(code: str) -> dict[str, str]:
    """The strings of one language."""
    text = resources.files(__package__).joinpath(f"{code}.json").read_text(encoding="utf-8")
    data: dict[str, str] = json.loads(text)
    return data


def _supported(value: str | None) -> str | None:
    """``"fr-FR"`` -> ``"fr"``; None when the language is not supported."""
    if not value:
        return None
    code = value.replace("_", "-").split("-")[0].strip().lower()
    return code if code in SUPPORTED else None


def set_language(value: str | None) -> str:
    """Select the language of everything a human reads. Returns the language in effect."""
    code = _supported(value) or DEFAULT
    _current.set(code)
    return code


def get_language() -> str:
    return _current.get()


@contextmanager
def use_language(value: str | None) -> Iterator[str]:
    """Temporarily switch language (tests, history pages written in another language)."""
    token = _current.set(_supported(value) or DEFAULT)
    try:
        yield _current.get()
    finally:
        _current.reset(token)


def resolve_language(explicit: str | None, env_value: str | None = None, locale: str | None = None) -> str:
    """``--language``, then ``$PLAINPROOF_LANGUAGE``, then the browser locale, else English."""
    for candidate in (explicit, env_value, locale):
        code = _supported(candidate)
        if code:
            return code
    return DEFAULT


def t(key: str, /, **fields: object) -> str:
    """The text of ``key`` in the current language (English when missing), placeholders filled."""
    text = catalog(get_language()).get(key) or catalog(DEFAULT).get(key) or key
    return text.format(**fields) if fields else text


def language_name(code: str | None = None) -> str:
    """English name of a language, as given to the model ("write your reasoning in French")."""
    return LANGUAGE_NAMES.get(code or get_language(), LANGUAGE_NAMES[DEFAULT])
