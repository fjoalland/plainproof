"""Paths as they may appear in a published report."""

from __future__ import annotations

from pathlib import Path


def display_path(path: Path | str | None) -> str:
    """A path for humans and published reports: relative to the working directory when it lies
    inside it, otherwise only its last two parts. An absolute path would reveal the layout of the
    machine that ran the tests (user name, temporary folders)."""
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return "/".join(p.parts[-2:])
