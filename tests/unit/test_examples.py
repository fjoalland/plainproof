"""The examples shipped with the repository stay loadable: scenarios, contexts and settings."""

from pathlib import Path

import pytest

from plainproof.config import find_config, load_config_file
from plainproof.scenario import load_scenarios

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize("folder", ["the-internet", "quickstart"])
def test_example_scenarios_load_without_any_variable(folder: str) -> None:
    scenarios = load_scenarios(str(EXAMPLES / folder), env={})
    assert scenarios
    assert all(s.steps for s in scenarios)


def test_the_internet_example() -> None:
    scenarios = {s.name: s for s in load_scenarios(str(EXAMPLES / "the-internet"), env={})}
    assert scenarios["05-canary-greeting"].expected_failure
    assert all("Dynamic Controls" in s.context for s in scenarios.values())
    config = find_config(EXAMPLES / "the-internet")
    assert config is not None
    assert load_config_file(config)["url"] == "https://the-internet.herokuapp.com/"
