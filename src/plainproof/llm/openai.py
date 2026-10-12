"""OpenAI Chat Completions, and every server that speaks the same API.

That covers OpenAI itself and most local or hosted alternatives: Ollama, LM Studio, vLLM,
llama.cpp server, OpenRouter, Groq, Together... (see the presets in ``registry.py``).
"""

from __future__ import annotations

from typing import Any

from .base import ChatRequest, ImagePart, LLMError, Part, TokenUsage
from .http import HttpClient, OptionalParam, data_url


class OpenAICompatibleClient(HttpClient):
    provider = "openai"
    default_base_url = "https://api.openai.com/v1"
    optional_params = (
        OptionalParam(("temperature",), ("temperature",)),
        OptionalParam(("response_format",), ("response_format", "json_object", "json_schema")),
    )
    image_url_as_string = False
    """Mistral wants ``"image_url": "data:..."`` where OpenAI wants ``{"url": "data:..."}``."""

    def _url(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def _part(self, part: Part) -> dict[str, Any]:
        if isinstance(part, ImagePart):
            url = data_url(part)
            return {"type": "image_url", "image_url": url if self.image_url_as_string else {"url": url}}
        return {"type": "text", "text": part.text}

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": [self._part(p) for p in m.parts]} for m in request.messages]
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if request.json_answer:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _parse(self, data: dict[str, Any]) -> tuple[str, TokenUsage]:
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"{self.name}: no answer in the response: {str(data)[:200]}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            text = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        else:
            text = content if isinstance(content, str) else ""
        if not text and message.get("refusal"):
            raise LLMError(f"{self.name}: the model refused: {message['refusal']}")
        usage = data.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        return text, TokenUsage(
            input_tokens=prompt - cached,
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_read_tokens=cached,
        )
