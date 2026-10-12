"""Settings: defaults, then plainproof.toml, then PLAINPROOF_* variables, then the command line."""

from pathlib import Path

import pytest

from plainproof.config import Settings, find_config, load_config_file, resolve_settings
from plainproof.errors import ConfigError
from plainproof.llm.pricing import Price


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults() -> None:
    settings = resolve_settings({}, env={}, file_values={})
    assert settings == Settings()
    assert settings.headless is True
    assert settings.max_steps == 30
    assert settings.viewport == (1280, 800)
    assert settings.temperature == 0.1
    assert settings.browser == "chromium"


def test_precedence_cli_then_env_then_file() -> None:
    file_values = {"model": "mistral", "url": "http://file/", "max_steps": 10, "locale": "fr-FR"}
    env = {"PLAINPROOF_MODEL": "gemini", "PLAINPROOF_URL": "http://env/"}
    settings = resolve_settings({"model": "anthropic", "url": None}, env=env, file_values=file_values)
    assert settings.model == "anthropic"  # command line
    assert settings.url == "http://env/"  # environment (the option was not given)
    assert settings.max_steps == 10  # file
    assert settings.locale == "fr-FR"


def test_environment_values_are_converted() -> None:
    env = {
        "PLAINPROOF_MAX_STEPS": "40",
        "PLAINPROOF_HEADLESS": "false",
        "PLAINPROOF_LABEL": "staging",
        "PLAINPROOF_LANGUAGE": "fr",
        "PLAINPROOF_LOCALE": "fr-FR",
        "PLAINPROOF_BROWSER": "firefox",
    }
    settings = resolve_settings({}, env=env, file_values={})
    assert (settings.max_steps, settings.headless, settings.label) == (40, False, "staging")
    assert (settings.language, settings.locale, settings.browser) == ("fr", "fr-FR", "firefox")


def test_a_bad_environment_value_is_reported() -> None:
    with pytest.raises(ConfigError, match="PLAINPROOF_MAX_STEPS"):
        resolve_settings({}, env={"PLAINPROOF_MAX_STEPS": "many"}, file_values={})


class TestFile:
    def test_full_file(self, tmp_path: Path) -> None:
        path = write(
            tmp_path / "plainproof.toml",
            """
model = "anthropic:claude-sonnet-5-5"
url = "https://staging.example.com"
max-steps = 40
headless = false
viewport = [1440, 900]
temperature = 0.2
vision = false
label = "staging"
context = "e2e/context.md"
out = "reports/latest"

[llm-options]
reasoning_effort = "low"

[pricing."anthropic:claude-sonnet-5-5"]
input = 1.5
output = 7.5
""",
        )
        settings = resolve_settings({}, env={}, file_values=load_config_file(path))
        assert settings.model == "anthropic:claude-sonnet-5-5"
        assert settings.max_steps == 40
        assert settings.headless is False
        assert settings.viewport == (1440, 900)
        assert settings.temperature == 0.2
        assert settings.vision is False
        assert settings.llm_options == {"reasoning_effort": "low"}
        assert settings.pricing == {"anthropic:claude-sonnet-5-5": Price(1.5, 7.5)}
        assert settings.context == tmp_path / "e2e" / "context.md", "paths are relative to the file"
        assert settings.out == tmp_path / "reports" / "latest"

    def test_an_unknown_key_lists_the_valid_ones(self, tmp_path: Path) -> None:
        path = write(tmp_path / "plainproof.toml", 'modle = "x"\n')
        with pytest.raises(ConfigError, match=r"modle.*model"):
            load_config_file(path)

    def test_a_wrong_type_is_reported(self, tmp_path: Path) -> None:
        path = write(tmp_path / "plainproof.toml", 'max_steps = "lots"\n')
        with pytest.raises(ConfigError, match="max_steps"):
            load_config_file(path)

    def test_invalid_toml(self, tmp_path: Path) -> None:
        path = write(tmp_path / "plainproof.toml", "model = \n")
        with pytest.raises(ConfigError, match=r"plainproof\.toml"):
            load_config_file(path)

    def test_a_price_needs_input_and_output(self, tmp_path: Path) -> None:
        path = write(tmp_path / "plainproof.toml", '[pricing."x:y"]\ninput = 1\n')
        with pytest.raises(ConfigError, match="pricing"):
            load_config_file(path)


def test_viewport_from_the_command_line() -> None:
    assert resolve_settings({"viewport": "1024x768"}, env={}, file_values={}).viewport == (1024, 768)
    with pytest.raises(ConfigError, match="viewport"):
        resolve_settings({"viewport": "big"}, env={}, file_values={})


def test_find_config_walks_up_to_the_repository_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    config = write(repo / "plainproof.toml", "")
    write(tmp_path / "plainproof.toml", "")  # above the repository: never used
    deep = repo / "e2e" / "billing"
    deep.mkdir(parents=True)
    assert find_config(deep) == config
    assert find_config(tmp_path / "missing" / "folder") == tmp_path / "plainproof.toml"
