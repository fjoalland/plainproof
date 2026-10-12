"""Google Gemini, through the Gemini API (generateContent)."""

from __future__ import annotations

from typing import Any

from .base import ChatRequest, ImagePart, LLMError, Part, TokenUsage
from .http import HttpClient, OptionalParam, b64


class GeminiClient(HttpClient):
    provider = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com"
    optional_params = (
        OptionalParam(("generationConfig", "temperature"), ("temperature",)),
        OptionalParam(
            ("generationConfig", "responseMimeType"),
            ("response_mime_type", "responsemimetype", "mime type", "json mode"),
        ),
    )

    def _url(self) -> str:
        return f"{self._base_url}/v1beta/models/{self.model}:generateContent"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key or ""}

    @staticmethod
    def _part(part: Part) -> dict[str, Any]:
        if isinstance(part, ImagePart):
            return {"inlineData": {"mimeType": part.media_type, "data": b64(part.data)}}
        return {"text": part.text}

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        config: dict[str, Any] = {}
        if self.temperature is not None:
            config["temperature"] = self.temperature
        if request.json_answer:
            config["responseMimeType"] = "application/json"
        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [self._part(p) for p in m.parts]}
                for m in request.messages
            ],
            "generationConfig": config,
        }

    def _parse(self, data: dict[str, Any]) -> tuple[str, TokenUsage]:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason") or str(data)[:200]
            raise LLMError(f"{self.name}: no answer (blocked: {reason})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(p.get("text", "")) for p in parts if not p.get("thought"))
        meta = data.get("usageMetadata") or {}
        prompt = int(meta.get("promptTokenCount") or 0)
        cached = int(meta.get("cachedContentTokenCount") or 0)
        output = int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0)
        return text, TokenUsage(input_tokens=prompt - cached, output_tokens=output, cache_read_tokens=cached)
