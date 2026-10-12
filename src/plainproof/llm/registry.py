"""Which model answers: ``provider:model`` specs, provider presets, API keys and plugins.

    anthropic:claude-sonnet-5-5     openai:gpt-6.1-sol        gemini:gemini-3.8-flash
    mistral:mistral-medium-latest   ollama:qwen2.5vl:7b       lmstudio:<model>
    openrouter:<vendor/model>       openai-compatible:<model> (with --base-url)

A provider alone (``--model anthropic``) selects its default model; a well-known model name
alone (``--model claude-haiku-5-5``) selects its provider. Other packages can add providers
through the ``plainproof.providers`` entry point group (see docs/llm-providers.md).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..errors import ConfigError
from .anthropic import AnthropicClient
from .base import LLMClient
from .gemini import GeminiClient
from .mistral import MistralClient
from .openai import OpenAICompatibleClient
from .scripted import ScriptedClient

ENTRY_POINT_GROUP = "plainproof.providers"


@dataclass(frozen=True)
class Provider:
    name: str
    factory: Callable[..., LLMClient]
    key_env: tuple[str, ...] = ()
    base_url: str = ""
    base_url_env: tuple[str, ...] = ()
    default_model: str | None = None
    needs_key: bool = True
    needs_base_url: bool = False
    model_prefixes: tuple[str, ...] = ()
    example: str = ""
    description: str = ""


def _scripted(model: str, **_: Any) -> LLMClient:
    return ScriptedClient.from_file(Path(model))


PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (
        Provider(
            "anthropic",
            AnthropicClient,
            key_env=("ANTHROPIC_API_KEY",),
            base_url_env=("ANTHROPIC_BASE_URL",),
            default_model="claude-sonnet-5-5",
            model_prefixes=("claude",),
            example="anthropic:claude-sonnet-5-5",
            description="Anthropic Claude",
        ),
        Provider(
            "openai",
            OpenAICompatibleClient,
            key_env=("OPENAI_API_KEY",),
            base_url_env=("OPENAI_BASE_URL",),
            default_model="gpt-6.1-sol",
            model_prefixes=("gpt-", "chatgpt", "o1", "o3", "o4"),
            example="openai:gpt-6.1-sol",
            description="OpenAI",
        ),
        Provider(
            "gemini",
            GeminiClient,
            key_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            base_url_env=("GEMINI_BASE_URL",),
            default_model="gemini-3.8-flash",
            model_prefixes=("gemini",),
            example="gemini:gemini-3.8-flash",
            description="Google Gemini",
        ),
        Provider(
            "mistral",
            MistralClient,
            key_env=("MISTRAL_API_KEY",),
            base_url_env=("MISTRAL_BASE_URL",),
            default_model="mistral-medium-latest",
            model_prefixes=("mistral", "ministral", "pixtral", "magistral", "codestral", "devstral"),
            example="mistral:mistral-medium-latest",
            description="Mistral AI",
        ),
        Provider(
            "ollama",
            OpenAICompatibleClient,
            base_url="http://localhost:11434/v1",
            base_url_env=("OLLAMA_BASE_URL",),
            needs_key=False,
            example="ollama:qwen2.5vl:7b",
            description="Ollama (local models)",
        ),
        Provider(
            "lmstudio",
            OpenAICompatibleClient,
            base_url="http://localhost:1234/v1",
            base_url_env=("LMSTUDIO_BASE_URL",),
            needs_key=False,
            example="lmstudio:<model>",
            description="LM Studio (local models)",
        ),
        Provider(
            "openrouter",
            OpenAICompatibleClient,
            key_env=("OPENROUTER_API_KEY",),
            base_url="https://openrouter.ai/api/v1",
            example="openrouter:<vendor/model>",
            description="OpenRouter (hundreds of hosted models)",
        ),
        Provider(
            "openai-compatible",
            OpenAICompatibleClient,
            key_env=("PLAINPROOF_API_KEY",),
            base_url_env=("PLAINPROOF_BASE_URL",),
            needs_key=False,
            needs_base_url=True,
            example="openai-compatible:<model> --base-url http://host:8000/v1",
            description="Any server speaking the OpenAI chat API (vLLM, llama.cpp, LiteLLM proxy...)",
        ),
        Provider(
            "scripted",
            _scripted,
            needs_key=False,
            example="scripted:answers.json",
            description="Answers read from a JSON file (tests, demos, offline checks)",
        ),
    )
}

# Providers chosen automatically when exactly one of their keys is set.
AUTO_DETECTED = ("anthropic", "openai", "gemini", "mistral")


class _EntryPoint(Protocol):
    @property
    def name(self) -> str: ...

    def load(self) -> Any: ...


def _plugin_entry_points() -> Iterable[_EntryPoint]:
    return metadata.entry_points(group=ENTRY_POINT_GROUP)


def _plugins() -> dict[str, _EntryPoint]:
    return {ep.name.lower(): ep for ep in _plugin_entry_points() if ep.name.lower() not in PROVIDERS}


def infer_provider(model: str) -> str | None:
    name = model.strip().lower()
    for provider in PROVIDERS.values():
        if any(name.startswith(prefix) for prefix in provider.model_prefixes):
            return provider.name
    return None


def parse_model_spec(spec: str) -> tuple[str, str]:
    """``"provider:model"`` (or a provider alone, or a well-known model alone) -> (provider, model)."""
    spec = spec.strip()
    head, sep, rest = spec.partition(":")
    head = head.strip().lower()
    known = set(PROVIDERS) | set(_plugins())
    if head in known:
        provider, model = head, rest.strip() if sep else ""
    else:
        inferred = infer_provider(spec)
        if inferred is None:
            raise ConfigError(
                f'Cannot tell which provider serves "{spec}": write it as provider:model, '
                "for example anthropic:claude-sonnet-5-5 or ollama:qwen2.5vl:7b (see `plainproof providers`)."
            )
        provider, model = inferred, spec
    if not model:
        preset = PROVIDERS.get(provider)
        if preset is None or preset.default_model is None:
            example = preset.example if preset else f"{provider}:<model>"
            raise ConfigError(f"{provider} needs a model name: {provider}:<model>, for example {example}.")
        model = preset.default_model
    return provider, model


def _has_key(provider: Provider, env: Mapping[str, str]) -> bool:
    return any(env.get(name) for name in provider.key_env)


def resolve_model(spec: str | None, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """The (provider, model) to use: the given spec, else the only provider whose key is set."""
    if spec:
        return parse_model_spec(spec)
    env = os.environ if env is None else env
    ready = [name for name in AUTO_DETECTED if _has_key(PROVIDERS[name], env)]
    if len(ready) == 1:
        return ready[0], PROVIDERS[ready[0]].default_model or ""
    if not ready:
        keys = ", ".join(PROVIDERS[name].key_env[0] for name in AUTO_DETECTED)
        raise ConfigError(
            "No model chosen. Use --model provider:model (or PLAINPROOF_MODEL), or set one API key "
            f"({keys}). For a local model: --model ollama:<model>. See `plainproof providers`."
        )
    raise ConfigError(
        f"Several API keys are set ({', '.join(ready)}): choose the model with --model, for example --model {ready[0]}."
    )


def create_client(
    spec: str | None,
    *,
    env: Mapping[str, str] | None = None,
    base_url: str | None = None,
    temperature: float | None = 0.1,
    vision: bool = True,
    options: Mapping[str, Any] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> LLMClient:
    """The client for ``spec``, configured from the environment (keys, base URLs)."""
    env = os.environ if env is None else env
    provider_name, model = resolve_model(spec, env)
    settings: dict[str, Any] = {"temperature": temperature, "vision": vision, "options": dict(options or {})}
    preset = PROVIDERS.get(provider_name)
    if preset is None:
        factory = _plugins()[provider_name].load()
        client: LLMClient = factory(model, base_url=base_url, **settings)
        return client
    key = next((env[name] for name in preset.key_env if env.get(name)), None)
    if preset.needs_key and not key:
        raise ConfigError(
            f"{provider_name} needs an API key: set {' or '.join(preset.key_env)} "
            "(in the environment or in a .env file)."
        )
    url = base_url or next((env[name] for name in preset.base_url_env if env.get(name)), None) or preset.base_url
    if preset.needs_base_url and not url:
        raise ConfigError(
            f"{provider_name} needs the base URL of the server: --base-url or PLAINPROOF_BASE_URL "
            "(for example http://localhost:8000/v1)."
        )
    auth_hint = f"Check {' or '.join(preset.key_env)}." if preset.key_env else ""
    return preset.factory(
        model,
        api_key=key,
        base_url=url or None,
        auth_hint=auth_hint,
        provider_name=provider_name,
        transport=transport,
        **settings,
    )


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    description: str
    ready: bool
    key_env: tuple[str, ...]
    default_model: str | None
    example: str


def provider_statuses(env: Mapping[str, str] | None = None) -> list[ProviderStatus]:
    """Every built-in provider, and whether it can be used as is (key set, or none needed)."""
    env = os.environ if env is None else env
    return [
        ProviderStatus(
            name=p.name,
            description=p.description,
            ready=not p.needs_key or _has_key(p, env),
            key_env=p.key_env,
            default_model=p.default_model,
            example=p.example,
        )
        for p in PROVIDERS.values()
    ]
