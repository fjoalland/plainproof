"""The JavaScript evaluated in the page, kept in ``scripts/*.js`` for readability."""

from __future__ import annotations

import functools
from importlib import resources


@functools.cache
def script(name: str) -> str:
    """The source of ``scripts/<name>.js``, without its full-line comments."""
    source = resources.files(__package__).joinpath("scripts").joinpath(f"{name}.js").read_text(encoding="utf-8")
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//")).strip()
