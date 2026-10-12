"""The command line, end to end, with a scripted model and fake browsers (no network, no Chromium)."""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar

import pytest
from typer.testing import CliRunner

from plainproof import __version__, cli
from plainproof.config import Settings
from tests.fakes import FakeBrowser

PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "PLAINPROOF_MODEL",
    "PLAINPROOF_LANGUAGE",
    "PLAINPROOF_URL",
    "PLAINPROOF_LABEL",
)
PASS = [{"step": 1, "action": "check", "text": "Welcome"}, {"step": 1, "action": "finish", "success": True}]
FAIL = [{"step": 1, "action": "finish", "success": False, "reason": "it broke"}]


class FakeLauncher:
    """Stands for BrowserLauncher: hands out fake browsers and remembers the settings."""

    instances: ClassVar[list[FakeLauncher]] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.browsers: list[FakeBrowser] = []
        FakeLauncher.instances.append(self)

    def __enter__(self) -> FakeLauncher:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    def session(self) -> FakeBrowser:
        browser = FakeBrowser(text="Welcome home")
        self.browsers.append(browser)
        return browser


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for key in PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    FakeLauncher.instances = []
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "make_launcher", FakeLauncher)


def invoke(*args: str) -> Any:
    return CliRunner().invoke(cli.app, list(args))


def scenario(tmp_path: Path, text: str = "Verify that Welcome is shown", name: str = "01-home") -> Path:
    folder = tmp_path / "e2e"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.txt").write_text(text, encoding="utf-8")
    return folder


def script(tmp_path: Path, answers: list[Any], name: str = "answers.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(answers), encoding="utf-8")
    return f"scripted:{path}"


def run(tmp_path: Path, answers: list[Any], *extra: str) -> Any:
    return invoke(
        "run",
        str(scenario(tmp_path)),
        "--model",
        script(tmp_path, answers),
        "--no-interpret",
        "--no-diagnose",
        "--out",
        "report",
        *extra,
    )


def test_version() -> None:
    result = invoke("--version")
    assert result.exit_code == 0
    assert __version__ in result.output


def test_a_passing_suite(tmp_path: Path) -> None:
    result = run(tmp_path, PASS, "--url", "http://app/", "--label", "staging")
    assert result.exit_code == 0, result.output
    assert "PASSED" in result.output
    assert "1 conform, 0 not conform" in result.output
    assert {"index.html", "summary.json", "junit.xml"} <= {p.name for p in (tmp_path / "report").iterdir()}
    assert (tmp_path / "e2e" / "recordings" / "01-home.json").is_file()
    assert FakeLauncher.instances[0].browsers[0].calls[0] == ("navigate", "http://app/")
    summary = json.loads((tmp_path / "report" / "summary.json").read_text(encoding="utf-8"))
    assert summary["label"] == "staging"
    assert summary["model"].startswith("scripted:")


def test_a_failing_suite_exits_with_1(tmp_path: Path) -> None:
    result = run(tmp_path, FAIL)
    assert result.exit_code == 1
    assert "FAILED" in result.output
    assert "it broke" in result.output


def test_browser_settings_reach_the_launcher(tmp_path: Path) -> None:
    run(tmp_path, PASS, "--headed", "--viewport", "1024x768", "--browser", "firefox", "--no-video", "--locale", "fr-FR")
    settings = FakeLauncher.instances[0].settings
    assert settings.headless is False
    assert settings.viewport == (1024, 768)
    assert settings.browser == "firefox"
    assert settings.video is False
    assert settings.locale == "fr-FR"


def test_the_browser_locale_picks_the_report_language(tmp_path: Path) -> None:
    result = run(tmp_path, PASS, "--locale", "fr-FR")
    assert "RÉUSSI" in result.output
    assert 'lang="fr"' in (tmp_path / "report" / "index.html").read_text(encoding="utf-8")


def test_no_model_and_no_key_explains_how_to_choose(tmp_path: Path) -> None:
    result = invoke("run", str(scenario(tmp_path)))
    assert result.exit_code == 2
    assert "No model chosen" in result.output


def test_a_missing_scenario_is_a_configuration_error() -> None:
    result = invoke("run", "e2e/nothing.txt", "--model", "ollama:x")
    assert result.exit_code == 2
    assert "not found" in result.output


def test_update_needs_an_existing_report(tmp_path: Path) -> None:
    result = run(tmp_path, PASS, "--update")
    assert result.exit_code == 2
    assert "--update" in result.output


def test_llm_options() -> None:
    assert cli.parse_llm_options(
        ["reasoning_effort=low", "max_tokens=500", "generationConfig.topK=1", "flag=true", 'stop=["x"]']
    ) == {
        "reasoning_effort": "low",
        "max_tokens": 500,
        "generationConfig": {"topK": 1},
        "flag": True,
        "stop": ["x"],
    }
    with pytest.raises(cli.ConfigError, match="KEY=VALUE"):
        cli.parse_llm_options(["oops"])


def test_a_settings_file_next_to_the_scenarios(tmp_path: Path) -> None:
    folder = scenario(tmp_path)
    (folder / "plainproof.toml").write_text('url = "http://from-file/"\nlabel = "from file"\n', encoding="utf-8")
    result = invoke("run", str(folder), "--model", script(tmp_path, PASS), "--no-interpret", "--out", "report")
    assert result.exit_code == 0, result.output
    assert FakeLauncher.instances[0].browsers[0].calls[0] == ("navigate", "http://from-file/")
    assert "plainproof.toml" in result.output


def test_replay_after_a_passing_run(tmp_path: Path) -> None:
    assert run(tmp_path, PASS).exit_code == 0
    result = invoke("replay", "e2e", "--out", "replayed")
    assert result.exit_code == 0, result.output
    assert "no model is called" in result.output
    summary = json.loads((tmp_path / "replayed" / "summary.json").read_text(encoding="utf-8"))
    assert summary["model"] == "replay"


def test_replay_without_recording_fails_that_scenario(tmp_path: Path) -> None:
    scenario(tmp_path)
    result = invoke("replay", "e2e", "--out", "replayed")
    assert result.exit_code == 1
    assert "run it once with a model" in result.output


def test_a_campaign_keeps_the_run_in_the_history(tmp_path: Path) -> None:
    result = invoke(
        "run",
        str(scenario(tmp_path)),
        "--model",
        script(tmp_path, PASS),
        "--no-interpret",
        "--campaign",
        "history",
        "--label",
        "v2",
        "--note",
        "after the upgrade",
        "--pin",
    )
    assert result.exit_code == 0, result.output
    campaigns = list((tmp_path / "history" / "campaigns").iterdir())
    assert len(campaigns) == 1
    meta = json.loads((campaigns[0] / "campaign.json").read_text(encoding="utf-8"))
    assert meta["label"] == "v2"
    assert meta["note"] == "after the upgrade"
    assert meta["pinned"] is True
    assert meta["mode"] == "model"
    assert (tmp_path / "history" / "index.html").is_file()
    rebuilt = invoke("history", "history", "--unpin", campaigns[0].name, "--title", "Shop")
    assert rebuilt.exit_code == 0, rebuilt.output
    assert "Shop" in (tmp_path / "history" / "index.html").read_text(encoding="utf-8")
    assert invoke("history", "history", "--pin", "nope").exit_code == 2


def test_providers_tell_which_keys_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "x")
    result = invoke("providers")
    assert result.exit_code == 0
    assert "anthropic" in result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "mistral-medium-latest" in result.output
    assert "key set" in result.output


def test_init_scaffolds_a_scenario_folder_without_overwriting(tmp_path: Path) -> None:
    result = invoke("init", "e2e")
    assert result.exit_code == 0, result.output
    names = {p.name for p in (tmp_path / "e2e").iterdir()}
    assert names == {"context.md", "01-example.txt", "plainproof.toml", ".env.example"}
    (tmp_path / "e2e" / "context.md").write_text("mine", encoding="utf-8")
    again = invoke("init", "e2e")
    assert "kept" in again.output
    assert (tmp_path / "e2e" / "context.md").read_text(encoding="utf-8") == "mine"


def test_a_freshly_initialised_folder_loads_without_any_variable(tmp_path: Path) -> None:
    from plainproof.scenario import load_scenarios

    assert invoke("init", "fresh").exit_code == 0
    (scenario,) = load_scenarios(str(tmp_path / "fresh"), env={})
    assert "Dashboard" in scenario.context
