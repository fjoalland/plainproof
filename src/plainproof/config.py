"""Settings of a run: defaults, then ``plainproof.toml``, then ``PLAINPROOF_*`` variables, then
the command line (each one overriding the previous).

``plainproof.toml`` is optional. It sits next to the scenarios or at the root of the
repository (it is looked up from the scenario folder upwards, up to the repository root), so
that a team shares its settings with its scenarios. Keys are the long option names of
``plainproof run`` (``max-steps`` or ``max_steps``), plus two tables:

.. code-block:: toml

    model = "anthropic:claude-sonnet-5-5"
    url = "https://staging.example.com"
    max-steps = 40

    [llm-options]                     # extra fields of the model request
    reasoning_effort = "low"

    [pricing."anthropic:claude-sonnet"]   # $ per million tokens, by model prefix
    input = 2.0
    output = 10.0
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .llm.pricing import Price

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

CONFIG_FILE = "plainproof.toml"
ENV_PREFIX = "PLAINPROOF_"


@dataclass
class Settings:
    # the model
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = 0.1
    vision: bool = True
    llm_options: dict[str, Any] = field(default_factory=dict)
    pricing: dict[str, Price] = field(default_factory=dict)
    # the browser
    url: str | None = None
    headless: bool = True
    browser: str = "chromium"
    viewport: tuple[int, int] = (1280, 800)
    locale: str = "en-US"
    slow_mo: int = 0
    video: bool = True
    # the run
    max_steps: int = 30
    interpret: bool = True
    diagnose: bool = True
    record: bool = True
    context: Path | None = None
    # the reports
    language: str | None = None
    label: str | None = None
    out: Path | None = None
    budget_mb: float = 90.0


# -- conversions ----------------------------------------------------------------------------------
def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ValueError("expected true or false")


def _int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("expected a whole number")
    return int(value)


def _float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("expected a number")
    return float(value)


def _optional_float(value: Any) -> float | None:
    if isinstance(value, str) and value.strip().lower() in ("", "none", "default"):
        return None
    return _float(value)


def _str(value: Any) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("expected a text")
    return str(value)


def _viewport(value: Any) -> tuple[int, int]:
    if isinstance(value, str):
        parts = value.lower().replace(" ", "").split("x")
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise ValueError("expected WIDTHxHEIGHT")
    if len(parts) != 2:
        raise ValueError("expected WIDTHxHEIGHT, for example 1280x800")
    width, height = (int(p) for p in parts)
    return width, height


_CONVERTERS: dict[str, Callable[[Any], Any]] = {
    "model": _str,
    "base_url": _str,
    "temperature": _optional_float,
    "vision": _bool,
    "url": _str,
    "headless": _bool,
    "browser": _str,
    "viewport": _viewport,
    "locale": _str,
    "slow_mo": _int,
    "video": _bool,
    "max_steps": _int,
    "interpret": _bool,
    "diagnose": _bool,
    "record": _bool,
    "context": Path,
    "language": _str,
    "label": _str,
    "out": Path,
    "budget_mb": _float,
}
_PATHS = ("context", "out")
# base_url is not read from PLAINPROOF_BASE_URL here: that variable belongs to the
# openai-compatible provider only (see llm/registry.py).
_ENV_FIELDS = tuple(name for name in _CONVERTERS if name != "base_url")


def _convert(name: str, value: Any, origin: str) -> Any:
    try:
        return _CONVERTERS[name](value)
    except (TypeError, ValueError) as err:
        raise ConfigError(f"{origin}: invalid value {value!r} for {name} ({err})") from None


# -- sources ---------------------------------------------------------------------------------------
def find_config(start: Path) -> Path | None:
    """The plainproof.toml of ``start`` or of its parents, up to the repository root."""
    folder = start.resolve()
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    for directory in [folder, *folder.parents]:
        candidate = directory / CONFIG_FILE
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            return None
    return None


def load_config_file(path: Path) -> dict[str, Any]:
    """The validated values of a plainproof.toml (paths made relative to its folder)."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise ConfigError(f"{path.name}: {err}") from None
    values: dict[str, Any] = {}
    for key, value in raw.items():
        name = key.replace("-", "_")
        if name == "llm_options":
            if not isinstance(value, dict):
                raise ConfigError(f"{path.name}: [llm-options] must be a table")
            values[name] = dict(value)
        elif name == "pricing":
            values[name] = _pricing(value, path)
        elif name in _CONVERTERS:
            converted = _convert(name, value, path.name)
            values[name] = path.parent / converted if name in _PATHS else converted
        else:
            valid = ", ".join(sorted({*_CONVERTERS, "llm_options", "pricing"}))
            raise ConfigError(f"{path.name}: unknown setting {key!r}. Valid settings: {valid}")
    return values


def _pricing(value: Any, path: Path) -> dict[str, Price]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path.name}: [pricing] must be a table of models")
    prices = {}
    for model, entry in value.items():
        try:
            prices[model] = Price(
                input=float(entry["input"]),
                output=float(entry["output"]),
                cache_read=float(entry["cache_read"]) if "cache_read" in entry else None,
                cache_write=float(entry["cache_write"]) if "cache_write" in entry else None,
            )
        except (KeyError, TypeError, ValueError):
            raise ConfigError(
                f'{path.name}: [pricing."{model}"] needs numbers for input and output ($ per million tokens)'
            ) from None
    return prices


def _from_env(env: Mapping[str, str]) -> dict[str, Any]:
    values = {}
    for name in _ENV_FIELDS:
        variable = ENV_PREFIX + name.upper()
        if env.get(variable):
            values[name] = _convert(name, env[variable], variable)
    return values


def resolve_settings(cli: Mapping[str, Any], env: Mapping[str, str], file_values: Mapping[str, Any]) -> Settings:
    """Settings from every source; ``cli`` holds the options given on the command line (None: not given)."""
    merged: dict[str, Any] = {**file_values, **_from_env(env)}
    for name, value in cli.items():
        if value is not None:
            merged[name] = _convert(name, value, "--" + name.replace("_", "-")) if name in _CONVERTERS else value
    known = {f.name for f in fields(Settings)}
    return Settings(**{name: value for name, value in merged.items() if name in known})
