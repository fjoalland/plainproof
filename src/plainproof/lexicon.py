"""Language heuristics behind the verdict guards.

The model interprets free wording; these patterns double-check it where a mistake would
turn a failing test green (an expectation reversed into an absence, a verification
silently skipped). They are deliberately small and conservative.

Scenarios may be written in any language: the patterns of every lexicon below are applied
together. To support a new language, add a :class:`Lexicon` to ``LEXICONS`` with its tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Lexicon:
    """How one language asks for a verification and expresses an absence."""

    verify: str
    """Words that turn a line into a verification ("check that", "I should see")."""
    negation: str
    """Words that express a negation or an absence ("no longer", "is gone")."""
    restriction: str = ""
    """Constructions that look negative but mean "only" (French "il ne reste que")."""


ENGLISH = Lexicon(
    verify=(
        r"\b(?:verify|verifies|check|checks|assert|asserts|ensure|ensures|make\s+sure|confirm\s+that"
        r"|expect|expects|expected"
        r"|should\s+(?:not\s+)?(?:see|show|display|contain|be|appear|read|say|remain|stay|include|list|have|get)"
        r"|must\s+(?:not\s+)?(?:see|show|display|contain|be|appear|read|say|remain|stay|include|list|have)"
        r"|(?:i|we|you)\s+(?:can\s+)?see)\b"
    ),
    negation=(
        r"\b(?:not|no|never|none|nothing|nobody|without|gone|disappear\w*|vanish\w*|missing|absent"
        r"|clos\w*|remov\w*|delet\w*|empty|cleared|hidden|hide\w*)\b|n['’]t\b"
    ),
    restriction=r"\bnothing\s+(?:else\s+)?but\b|\bno\s+(?:more|less|fewer)\s+than\b|\bnot\s+only\b",
)

FRENCH = Lexicon(
    verify=(
        r"\b(?:v[ée]rifie[rsz]?|s'assurer|contr[ôo]le[rz]?|je\s+vois|on\s+voit|je\s+constate|on\s+constate"
        r"|(?:je\s+|on\s+|il\s+)?doi[st]\s+voir|doivent\s+voir"
        r"|(?:ne\s+)?doi(?:t|vent)\s+(?:plus\s+|pas\s+|toujours\s+|bien\s+)?"
        r"(?:contenir|afficher|appara[îi]tre|s'afficher|[êe]tre|voir|rester|indiquer|mentionner))\b"
    ),
    negation=(
        r"\b(?:pas|plus|aucun|aucune|jamais|ni|sans|rien|personne|disparu|disparue|dispara[îi]t|absent|absente"
        r"|manque|ferm\w*|referm\w*|vide|vid[eé]\w*|supprim\w*|effac\w*|retir\w*|enl[eè]v\w*)\b|\bn['’]|\bne\b"
    ),
    # "Il n'y a plus qu'une fiche", "il ne reste que X": a restriction ("only X"), not a negation.
    restriction=r"\bn(?:e\b|['’])\s*(?:\S+\s+){0,4}?(?:plus\s+)?qu(?:e\b|['’])",
)

LEXICONS: tuple[Lexicon, ...] = (ENGLISH, FRENCH)


def _union(patterns: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns if p), re.IGNORECASE)


_VERIFY_RE = _union([lex.verify for lex in LEXICONS])
_NEGATION_RE = _union([lex.negation for lex in LEXICONS])
_RESTRICTION_RE = _union([lex.restriction for lex in LEXICONS])


def asks_verification(line: str) -> bool:
    """True when a scenario line asks to verify something, whatever the wording."""
    return bool(_VERIFY_RE.search(line or ""))


def says_absent(line: str) -> bool:
    """True when a line expresses a negation or an absence somewhere.

    Restrictions ("nothing but X", "il ne reste que X") mean "only X" and do not count:
    one was seen turned into "X is no longer shown", reversing the test.
    """
    return bool(_NEGATION_RE.search(_RESTRICTION_RE.sub(" ", line or "")))
