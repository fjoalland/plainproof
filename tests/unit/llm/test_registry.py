"""Choosing a provider and a model: "provider:model" specs, defaults, keys, plugins."""

from pathlib import Path
from typing import Any

import pytest

from plainproof.errors import ConfigError
from plainproof.llm import registry
from plainproof.llm.anthropic import AnthropicClient
from plainproof.llm.base import ChatRequest, Completion, TokenUsage
from plainproof.llm.gemini import GeminiClient
from plainproof.llm.mistral import MistralClient
from plainproof.llm.openai import OpenAICompatibleClient
from plainproof.llm.registry import create_client, parse_model_spec, provider_statuses, resolve_model
from plainproof.llm.scripted import ScriptedClient


class TestParseModelSpec:
    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("anthropic:claude-sonnet-5-5", ("anthropic", "claude-sonnet-5-5")),
            ("ollama:qwen2.5vl:7b", ("ollama", "qwen2.5vl:7b")),  # the model name has a colon too
            ("openrouter:google/gemini-3.8-flash", ("openrouter", "google/gemini-3.8-flash")),
            ("claude-haiku-5-5", ("anthropic", "claude-haiku-5-5")),  # provider inferred
            ("gpt-6-luna", ("openai", "gpt-6-luna")),
            ("o4-mini", ("openai", "o4-mini")),
            ("gemini-3.8-flash", ("gemini", "gemini-3.8-flash")),
            ("mistral-small-latest", ("mistral", "mistral-small-latest")),
            ("pixtral-large-latest", ("mistral", "pixtral-large-latest")),
            ("anthropic", ("anthropic", "claude-sonnet-5-5")),  # provider alone: its default model
            ("  Gemini : gemini-flash-latest ", ("gemini", "gemini-flash-latest")),
        ],
    )
    def test_specs(self, spec: str, expected: tuple[str, str]) -> None:
        assert parse_model_spec(spec) == expected

    def test_a_local_provider_needs_a_model_name(self) -> None:
        with pytest.raises(ConfigError, match=r"ollama:<model>"):
            parse_model_spec("ollama")

    def test_unknown_model_names_ask_for_a_provider(self) -> None:
        with pytest.raises(ConfigError, match="provider:model"):
            parse_model_spec("llava-13b")


class TestResolveModel:
    def test_an_explicit_spec_wins(self) -> None:
        assert resolve_model("gemini", {"ANTHROPIC_API_KEY": "k"}) == ("gemini", "gemini-3.8-flash")

    def test_the_only_provider_with_a_key_is_chosen(self) -> None:
        assert resolve_model(None, {"MISTRAL_API_KEY": "k"}) == ("mistral", "mistral-medium-latest")

    def test_no_key_at_all_explains_how_to_choose(self) -> None:
        with pytest.raises(ConfigError, match=r"--model.*ANTHROPIC_API_KEY.*OPENAI_API_KEY"):
            resolve_model(None, {})

    def test_several_keys_ask_to_choose(self) -> None:
        with pytest.raises(ConfigError, match="anthropic, openai"):
            resolve_model(None, {"OPENAI_API_KEY": "a", "ANTHROPIC_API_KEY": "b"})


class TestCreateClient:
    def test_hosted_providers_get_their_key_and_a_hint(self) -> None:
        client = create_client("anthropic:claude-opus-5-5", env={"ANTHROPIC_API_KEY": "sk-ant"})
        assert isinstance(client, AnthropicClient)
        assert client.name == "anthropic:claude-opus-5-5"
        assert client._api_key == "sk-ant"
        assert "ANTHROPIC_API_KEY" in client._auth_hint

    @pytest.mark.parametrize(
        ("spec", "env", "cls"),
        [
            ("openai:gpt-6-luna", {"OPENAI_API_KEY": "k"}, OpenAICompatibleClient),
            ("gemini", {"GOOGLE_API_KEY": "k"}, GeminiClient),  # the second accepted variable
            ("mistral", {"MISTRAL_API_KEY": "k"}, MistralClient),
            ("ollama:gemma3", {}, OpenAICompatibleClient),
        ],
    )
    def test_each_provider_gets_its_client(self, spec: str, env: dict[str, str], cls: type) -> None:
        assert type(create_client(spec, env=env)) is cls

    def test_a_missing_key_names_the_variable(self) -> None:
        with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
            create_client("openai:gpt-6-luna", env={})

    def test_local_servers_have_a_default_address_that_env_or_option_override(self) -> None:
        assert create_client("ollama:gemma3", env={})._base_url == "http://localhost:11434/v1"
        assert create_client("lmstudio:qwen", env={})._base_url == "http://localhost:1234/v1"
        moved = create_client("ollama:gemma3", env={"OLLAMA_BASE_URL": "http://gpu-box:11434/v1"})
        assert moved._base_url == "http://gpu-box:11434/v1"
        explicit = create_client("ollama:gemma3", env={}, base_url="http://other/v1")
        assert explicit._base_url == "http://other/v1"

    def test_any_openai_compatible_server(self) -> None:
        with pytest.raises(ConfigError, match="base URL"):
            create_client("openai-compatible:my-model", env={})
        client = create_client(
            "openai-compatible:my-model", env={"PLAINPROOF_BASE_URL": "https://llm.corp/v1", "PLAINPROOF_API_KEY": "x"}
        )
        assert client.name == "openai-compatible:my-model"
        assert client._base_url == "https://llm.corp/v1"
        assert client._api_key == "x"

    def test_settings_are_passed_through(self) -> None:
        client = create_client(
            "openai:gpt-6-luna",
            env={"OPENAI_API_KEY": "k"},
            temperature=None,
            vision=False,
            options={"reasoning_effort": "low"},
        )
        assert client.temperature is None
        assert client.vision is False
        assert client._options == {"reasoning_effort": "low"}

    def test_scripted_answers_from_a_file(self, tmp_path: Path) -> None:
        script = tmp_path / "answers.json"
        script.write_text('[{"action": "finish", "success": true, "reason": "ok"}]', encoding="utf-8")
        client = create_client(f"scripted:{script}", env={})
        assert isinstance(client, ScriptedClient)
        assert '"finish"' in client.complete(ChatRequest.single(system="s", text="t")).text

    def test_third_party_providers_plug_in_through_entry_points(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class EchoClient:
            def __init__(self, model: str, **settings: Any) -> None:
                self.model, self.settings = model, settings

            name = property(lambda self: f"echo:{self.model}")
            vision = True

            def complete(self, request: ChatRequest) -> Completion:
                return Completion(text="{}", usage=TokenUsage())

        class EntryPoint:
            name = "echo"

            @staticmethod
            def load() -> type[EchoClient]:
                return EchoClient

        monkeypatch.setattr(registry, "_plugin_entry_points", lambda: [EntryPoint()])
        client = create_client("echo:v1", env={}, temperature=0.3)
        assert isinstance(client, EchoClient)
        assert client.name == "echo:v1"
        assert client.settings["temperature"] == 0.3


def test_provider_statuses_tell_which_keys_are_set() -> None:
    statuses = {s.name: s for s in provider_statuses({"MISTRAL_API_KEY": "k"})}
    assert statuses["mistral"].ready
    assert statuses["mistral"].default_model == "mistral-medium-latest"
    assert not statuses["anthropic"].ready
    assert statuses["anthropic"].key_env == ("ANTHROPIC_API_KEY",)
    assert statuses["ollama"].ready  # local: no key needed
