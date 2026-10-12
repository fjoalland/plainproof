"""Scenarios and project contexts.

A scenario is a ``.txt`` file written in plain language by whoever knows the application:
what they do, what they expect to see. Lines starting with ``#`` are comments for humans
(they become the scenario's description in reports); ``# expect: failure`` marks a scenario
that must fail (a canary checking that a known defect is caught).

A project context is a ``context.md`` written once by the team that knows the application:
how to log in, where each screen is, the vocabulary. Every ``context.md`` from the scenario's
folder up to the repository root applies, outermost first.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .secrets import MissingVariablesError, Secrets, expand_variables

CONTEXT_FILE = "context.md"
SCENARIO_SUFFIX = ".txt"
RECORDINGS_DIR = "recordings"
INLINE_NAME = "inline"

_EXPECTED_FAILURE_RE = re.compile(r"^\s*#\s*expect(?:ed)?\s*[:=]\s*fail(?:ure|s|ed)?\s*$", re.IGNORECASE)


class ScenarioError(ConfigError, ValueError):
    """A scenario or a context that cannot be loaded (missing file, missing variable...)."""


@dataclass(frozen=True)
class Scenario:
    name: str
    source: str
    """As written, comment lines removed, variables not expanded: what reports show."""
    text: str
    """Plain variables expanded, secrets kept as placeholders: what the model reads."""
    path: Path | None = None
    context: str = ""
    secrets: Secrets = field(default_factory=Secrets)
    description: str = ""
    expected_failure: bool = False

    @property
    def steps(self) -> list[str]:
        """One non-empty line = one step."""
        return lines_of(self.text)


def lines_of(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _looks_like_path(target: str) -> bool:
    if "\n" in target:
        return False
    stripped = target.strip()
    return stripped.endswith((SCENARIO_SUFFIX, "/", "\\")) or (
        any(sep in stripped for sep in "/\\") and not any(c.isspace() for c in stripped)
    )


def _parse(raw: str) -> tuple[str, str, bool]:
    """(source without comments, description, expected failure).

    The description is the comment block above the first step; comments further down are
    notes for whoever maintains the scenario.
    """
    body: list[str] = []
    header: list[str] = []
    expected_failure = False
    for line in raw.splitlines():
        if line.lstrip().startswith("#"):
            if _EXPECTED_FAILURE_RE.match(line):
                expected_failure = True
            elif not any(body):
                header.append(line.lstrip()[1:].strip())
        else:
            body.append(line.rstrip())
    return "\n".join(body).strip(), " ".join(n for n in header if n), expected_failure


def find_contexts(folder: Path) -> list[Path]:
    """Context files that apply to the scenarios of ``folder``, outermost first: the one of
    ``folder`` and those of its parents, up to the repository root (the folder holding .git)."""
    found = []
    for directory in [folder.resolve(), *folder.resolve().parents]:
        candidate = directory / CONTEXT_FILE
        if candidate.is_file():
            found.append(candidate)
        if (directory / ".git").exists():
            break
    return found[::-1]


def load_context(path: Path, env: Mapping[str, str]) -> tuple[str, Secrets]:
    """A context file with its variables expanded like a scenario's."""
    try:
        return expand_variables(path.read_text(encoding="utf-8").strip(), env)
    except MissingVariablesError as err:
        raise ScenarioError(f"{path.name}: {err}") from None


def _expand(raw: str, env: Mapping[str, str], origin: str) -> tuple[str, Secrets]:
    try:
        return expand_variables(raw, env)
    except MissingVariablesError as err:
        raise ScenarioError(f"{origin}: {err}") from None


def _load_file(path: Path, env: Mapping[str, str], name: str) -> Scenario:
    source, description, expected_failure = _parse(path.read_text(encoding="utf-8"))
    if not source:
        raise ScenarioError(f"Scenario file is empty: {path}")
    text, secrets = _expand(source, env, path.name)
    return Scenario(
        name=name,
        source=source,
        text=text,
        path=path,
        secrets=secrets,
        description=description,
        expected_failure=expected_failure,
    )


def _scenario_files(folder: Path) -> list[Path]:
    """Every scenario of a folder tree, by relative path; hidden folders and recordings excluded."""
    files = []
    for file in folder.rglob(f"*{SCENARIO_SUFFIX}"):
        parts = file.relative_to(folder).parts
        if any(p.startswith(".") or p == RECORDINGS_DIR for p in parts[:-1]):
            continue
        files.append(file)
    return sorted(files, key=lambda f: f.relative_to(folder).as_posix())


def _flat_name(file: Path, root: Path) -> str:
    """``billing/01-invoice.txt`` -> ``billing-01-invoice``: each scenario gets one report folder."""
    return "-".join([*file.relative_to(root).parent.parts, file.stem])


def _with_context(scenario: Scenario, contexts: list[Path], env: Mapping[str, str]) -> Scenario:
    if not contexts:
        return scenario
    loaded = [load_context(path, env) for path in contexts]
    secrets = scenario.secrets
    for _, context_secrets in loaded:
        secrets = context_secrets.merge(secrets)
    return Scenario(
        name=scenario.name,
        source=scenario.source,
        text=scenario.text,
        path=scenario.path,
        context="\n\n".join(text for text, _ in loaded),
        secrets=secrets,
        description=scenario.description,
        expected_failure=scenario.expected_failure,
    )


def load_scenarios(
    target: str, env: Mapping[str, str] | None = None, context_path: Path | None = None
) -> list[Scenario]:
    """Scenarios of ``target``: a folder (every ``.txt`` of its tree), a file, or inline text.

    ``context_path`` replaces the ``context.md`` files found next to the scenarios.
    Raises :class:`ScenarioError` with a message meant for the user.
    """
    env = os.environ if env is None else env
    path = Path(target)
    if path.is_dir():
        files = _scenario_files(path)
        if not files:
            raise ScenarioError(f"No {SCENARIO_SUFFIX} scenario found in {target}")
        scenarios = [_load_file(f, env, _flat_name(f, path)) for f in files]
    elif path.is_file():
        scenarios = [_load_file(path, env, path.stem)]
    elif _looks_like_path(target):
        raise ScenarioError(f"Scenario file or folder not found: {target}")
    else:
        source, description, expected_failure = _parse(target)
        text, secrets = _expand(source, env, INLINE_NAME)
        scenarios = [
            Scenario(
                name=INLINE_NAME,
                source=source,
                text=text,
                secrets=secrets,
                description=description,
                expected_failure=expected_failure,
            )
        ]
    result = []
    for scenario in scenarios:
        if context_path is not None:
            contexts = [context_path]
        elif scenario.path is not None:
            contexts = find_contexts(scenario.path.parent)
        else:
            contexts = []
        result.append(_with_context(scenario, contexts, env))
    return result
