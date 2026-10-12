"""Variables and secrets in scenarios and project contexts.

Scenarios reference environment variables as ``${NAME}``. A plain variable is replaced by
its value before anything reaches the model. A *secret* variable (its name contains
PASSWORD, PASS, PWD, SECRET, TOKEN or KEY) is kept as the ``${NAME}`` placeholder: the model
types the placeholder, and the real value is substituted only when the browser performs the
action. Everything that is written or logged goes through :meth:`Secrets.redact`, which puts
the placeholder back wherever the value would have appeared.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_NAME_RE = re.compile(r"PASS|PWD|SECRET|TOKEN|KEY", re.IGNORECASE)


def is_secret_name(name: str) -> bool:
    """True for a variable whose value must never be shown to the model nor written anywhere."""
    return bool(_SECRET_NAME_RE.search(name))


class MissingVariablesError(KeyError):
    """Variables referenced by a scenario or a context but absent from the environment."""

    def __init__(self, names: list[str] | tuple[str, ...]) -> None:
        self.names = tuple(sorted(set(names)))
        super().__init__(self.names)

    def __str__(self) -> str:
        return f"Missing environment variable(s): {', '.join(self.names)}"


class Secrets:
    """The secret placeholders of a scenario: ``{NAME: value}``."""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = {name: value for name, value in (values or {}).items() if value}
        # Longest first, so that a secret containing another one is hidden whole.
        self._by_length = sorted(self._values.items(), key=lambda item: len(item[1]), reverse=True)

    def __bool__(self) -> bool:
        return bool(self._values)

    def __repr__(self) -> str:  # never print the values
        return f"Secrets({', '.join(self._values)})"

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._values)

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(self._values.values())

    def merge(self, other: Secrets) -> Secrets:
        return Secrets({**self._values, **other._values})

    def substitute(self, text: str) -> str:
        """Placeholders replaced by the real values: only for the browser, at execution time."""
        if not self._values or "${" not in text:
            return text
        return PLACEHOLDER_RE.sub(lambda m: self._values.get(m.group(1), m.group(0)), text)

    def hide(self, text: str) -> str:
        """Real values replaced by their placeholders."""
        for name, value in self._by_length:
            text = text.replace(value, "${" + name + "}")
        return text

    def redact(self, value: Any) -> Any:
        """:meth:`hide` applied to every string of a nested structure (dicts, lists, tuples)."""
        if not self._values:
            return value
        if isinstance(value, str):
            return self.hide(value)
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        return value


def expand_variables(raw: str, env: Mapping[str, str]) -> tuple[str, Secrets]:
    """Replace ``${NAME}`` by its value from ``env``, except secrets which stay placeholders.

    Raises :class:`MissingVariablesError` listing every variable absent from ``env``.
    """
    missing: list[str] = []
    secrets: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in env:
            missing.append(name)
            return match.group(0)
        value = env[name]
        if is_secret_name(name) and value:
            secrets[name] = value
            return match.group(0)
        return value

    text = PLACEHOLDER_RE.sub(replace, raw)
    if missing:
        raise MissingVariablesError(missing)
    return text, Secrets(secrets)
