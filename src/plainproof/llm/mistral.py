"""Mistral AI: the OpenAI-style API, with images given as a plain data URL."""

from __future__ import annotations

from .openai import OpenAICompatibleClient


class MistralClient(OpenAICompatibleClient):
    provider = "mistral"
    default_base_url = "https://api.mistral.ai/v1"
    image_url_as_string = True
