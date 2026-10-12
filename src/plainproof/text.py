"""Text helpers shared by the browser, the agent and the replay.

Every comparison between what a scenario says and what a page shows goes through
:func:`normalize` or :func:`squash`, so that case, accents, spacing, quote marks and
a badly encoded server answer never decide a verdict.
"""

from __future__ import annotations

import re
import unicodedata

# UTF-8 bytes decoded as Latin-1 by a misconfigured server: "é" arrives as "Ã©".
_MOJIBAKE_RE = re.compile("[Â-ô][\u0080-¿]{1,3}")


def _unmojibake(text: str) -> str:
    def fix(match: re.Match[str]) -> str:
        try:
            return match.group(0).encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return match.group(0)

    return _MOJIBAKE_RE.sub(fix, text)


def normalize(text: str) -> str:
    """Lowercase, without accents, whitespace collapsed: ``"Été  Crème"`` -> ``"ete creme"``."""
    decomposed = unicodedata.normalize("NFKD", _unmojibake(text))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def squash(text: str) -> str:
    """Letters and digits only: a quote survives quote marks, punctuation and spacing."""
    return re.sub(r"[^a-z0-9]+", "", normalize(text))


def truthy(value: object) -> bool:
    """Lenient boolean for values written by a model: ``true``, ``"true"``, ``"1"``, ``"yes"``..."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "oui")


# The exact things a step names: quoted wording, dates, placeholders, numbers and identifiers.
_ANCHOR_RE = re.compile(
    r'"([^"]{2,})"|«\s*([^»]{2,}?)\s*»|“([^”]{2,})”'  # quoted wording
    r"|(\b\d{4}-\d{2}-\d{2}\b)"  # ISO dates
    r"|(\b\d{1,2}/\d{1,2}/\d{2,4}\b)"  # dd/mm/yyyy and mm/dd/yyyy
    r"|(\$\{[A-Za-z_][A-Za-z0-9_]*\})"  # ${PLACEHOLDER}
    r"|(\b[A-Za-z]*\d[A-Za-z0-9]*\d[A-Za-z0-9]*\b)"  # numbers and identifiers (two digits or more)
)

# A capitalised word that does not start a sentence: a label, a menu, a name ("Settings").
# The second character must be a letter, so "I'm" and "I'll" are not labels.
_NAMED_RE = re.compile(r"(?<![.!?:]\s)(?<!^)\b([A-ZÀ-Ý][A-Za-zÀ-ÿ][\wÀ-ÿ'’-]+)")
_QUOTED_RE = re.compile(r'"[^"]*"|«[^»]*»|“[^”]*”')


def anchors(text: str) -> list[str]:
    """Quoted wording, dates, placeholders, numbers and identifiers of a step, in order.

    A text check proves a verification step only when it looks for one of them: looking
    for a vaguer fragment ("error", "end date") could match a field label and prove nothing.
    """
    return [next(group for group in match.groups() if group) for match in _ANCHOR_RE.finditer(text)]


def labels(text: str) -> list[str]:
    """The capitalised labels a sentence names ("Settings", "Partners"), outside quotations."""
    return _NAMED_RE.findall(_QUOTED_RE.sub(" _ ", text.strip()))


def named_values(text: str) -> list[str]:
    """Everything a sentence names exactly: its anchors, then its labels."""
    return anchors(text) + labels(text)


def anchor_hit(step_text: str, squashed_target: str) -> bool:
    """True when one of the exact values of a step appears in an action's (squashed) target."""
    return any(len(squash(a)) >= 2 and squash(a) in squashed_target for a in anchors(step_text))
