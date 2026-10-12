"""Anthropic Claude, through the Messages API."""

from __future__ import annotations

from typing import Any

from .base import ChatRequest, ImagePart, Part, TokenUsage
from .http import HttpClient, OptionalParam, b64

API_VERSION = "2023-06-01"


class AnthropicClient(HttpClient):
    provider = "anthropic"
    default_base_url = "https://api.anthropic.com"
    optional_params = (OptionalParam(("temperature",), ("temperature",)),)

    def _url(self) -> str:
        return f"{self._base_url}/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key or "", "anthropic-version": API_VERSION}

    @staticmethod
    def _block(part: Part) -> dict[str, Any]:
        if isinstance(part, ImagePart):
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": part.media_type, "data": b64(part.data)},
            }
        return {"type": "text", "text": part.text}

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            # The system prompt (rules + project context) is identical at every turn of a run:
            # caching it makes every call after the first one much cheaper.
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": m.role, "content": [self._block(p) for p in m.parts]} for m in request.messages],
        }
        # JSON is asked for by the prompt (and read leniently): no response format parameter needed.
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        return payload

    def _parse(self, data: dict[str, Any]) -> tuple[str, TokenUsage]:
        text = "".join(str(b.get("text", "")) for b in data.get("content") or [] if b.get("type") == "text")
        usage = data.get("usage") or {}
        return text, TokenUsage(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        )
