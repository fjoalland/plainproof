"""Provider adapters: exact request format, answer and token reading, retries and fallbacks.

No network: every test talks to a scripted server through httpx's MockTransport.
"""

import base64
from typing import Any

import pytest

from plainproof.llm.anthropic import AnthropicClient
from plainproof.llm.base import ChatRequest, LLMClient, LLMError, TokenUsage
from plainproof.llm.gemini import GeminiClient
from plainproof.llm.mistral import MistralClient
from plainproof.llm.openai import OpenAICompatibleClient

from .fake_server import FakeServer, NetworkDown, error, ok

PNG = b"\x89PNG fake"
B64 = base64.b64encode(PNG).decode()
REQUEST = ChatRequest.single(system="You test web apps.", text="Next action?", image=PNG)


def openai_answer(content: Any = '{"action": "click"}', **usage: Any) -> dict[str, Any]:
    return {
        "model": "gpt-test",
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 7, **usage},
    }


def openai(server: FakeServer, **kwargs: Any) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        "gpt-test", api_key="sk-test", transport=server.transport, sleep=server.sleep, **kwargs
    )


class TestOpenAICompatible:
    def test_is_an_llm_client(self) -> None:
        assert isinstance(openai(FakeServer()), LLMClient)
        assert openai(FakeServer()).name == "openai:gpt-test"

    def test_request_format(self) -> None:
        server = FakeServer(ok(openai_answer()))
        openai(server).complete(REQUEST)
        request = server.requests[0]
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-test"
        assert server.body() == {
            "model": "gpt-test",
            "messages": [
                {"role": "system", "content": "You test web apps."},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{B64}"}},
                        {"type": "text", "text": "Next action?"},
                    ],
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

    def test_answer_and_usage_with_cached_tokens(self) -> None:
        server = FakeServer(ok(openai_answer(prompt_tokens_details={"cached_tokens": 60})))
        completion = openai(server).complete(REQUEST)
        assert completion.text == '{"action": "click"}'
        assert completion.usage == TokenUsage(input_tokens=40, output_tokens=7, cache_read_tokens=60)

    def test_answer_given_as_content_parts(self) -> None:
        server = FakeServer(ok(openai_answer([{"type": "text", "text": '{"a":'}, {"type": "text", "text": "1}"}])))
        assert openai(server).complete(REQUEST).text == '{"a":1}'

    def test_a_refusal_is_an_error(self) -> None:
        answer = openai_answer(None)
        answer["choices"][0]["message"]["refusal"] = "I can't help with that."
        with pytest.raises(LLMError, match="can't help"):
            openai(FakeServer(ok(answer))).complete(REQUEST)

    def test_an_answer_without_choices_is_an_error(self) -> None:
        with pytest.raises(LLMError, match="no answer"):
            openai(FakeServer(ok({"choices": []}))).complete(REQUEST)

    def test_custom_server_without_key_temperature_or_json_mode(self) -> None:
        server = FakeServer(ok(openai_answer()))
        client = OpenAICompatibleClient(
            "qwen2.5vl:7b",
            base_url="http://localhost:11434/v1/",
            temperature=None,
            transport=server.transport,
            provider_name="ollama",
        )
        client.complete(ChatRequest(system="s", messages=REQUEST.messages, json_answer=False))
        assert str(server.requests[0].url) == "http://localhost:11434/v1/chat/completions"
        assert "authorization" not in server.requests[0].headers
        assert "temperature" not in server.body()
        assert "response_format" not in server.body()
        assert client.name == "ollama:qwen2.5vl:7b"

    def test_extra_options_are_merged_into_the_payload(self) -> None:
        server = FakeServer(ok(openai_answer()))
        openai(server, options={"reasoning_effort": "low", "temperature": 0}).complete(REQUEST)
        assert server.body()["reasoning_effort"] == "low"
        assert server.body()["temperature"] == 0  # an explicit option wins


class TestRetries:
    def test_rate_limit_waits_as_told_then_succeeds(self) -> None:
        server = FakeServer(error(429, "slow down", headers={"retry-after": "3"}), ok(openai_answer()))
        assert openai(server).complete(REQUEST).text
        assert server.sleeps == [3.0]

    def test_overload_and_network_errors_back_off_exponentially(self) -> None:
        server = FakeServer(error(503), NetworkDown(), error(529), ok(openai_answer()))
        assert openai(server).complete(REQUEST).text
        assert server.sleeps == [1.0, 2.0, 4.0]

    def test_gives_up_after_the_last_attempt(self) -> None:
        server = FakeServer(*[error(500, "boom")] * 3)
        with pytest.raises(LLMError, match="boom") as err:
            openai(server, max_attempts=3).complete(REQUEST)
        assert err.value.transient
        assert err.value.status == 500
        assert len(server.requests) == 3

    def test_retry_after_is_capped(self) -> None:
        server = FakeServer(error(429, headers={"retry-after": "3600"}), ok(openai_answer()))
        openai(server).complete(REQUEST)
        assert server.sleeps == [60.0]

    def test_bad_key_fails_at_once_with_a_hint(self) -> None:
        server = FakeServer(error(401, "invalid api key"))
        with pytest.raises(LLMError, match=r"invalid api key.*OPENAI_API_KEY") as err:
            openai(server, auth_hint="Check OPENAI_API_KEY.").complete(REQUEST)
        assert not err.value.transient
        assert len(server.requests) == 1

    def test_unsupported_temperature_is_dropped_for_good(self) -> None:
        server = FakeServer(
            error(400, "Unsupported value: 'temperature' does not support 0.1 with this model."),
            ok(openai_answer()),
            ok(openai_answer()),
        )
        client = openai(server)
        client.complete(REQUEST)
        client.complete(REQUEST)
        assert "temperature" in server.body(0)
        assert "temperature" not in server.body(1)
        assert "temperature" not in server.body(2)
        assert server.sleeps == []

    def test_unsupported_json_mode_is_dropped(self) -> None:
        server = FakeServer(error(400, "'response_format.type' must be 'json_schema'"), ok(openai_answer()))
        openai(server).complete(REQUEST)
        assert "response_format" not in server.body(1)

    def test_other_bad_requests_fail(self) -> None:
        server = FakeServer(error(400, "image too large"))
        with pytest.raises(LLMError, match="image too large"):
            openai(server).complete(REQUEST)

    def test_a_non_json_body_is_an_error(self) -> None:
        import httpx

        server = FakeServer(httpx.Response(200, text="<html>proxy page</html>"))
        with pytest.raises(LLMError, match="not JSON"):
            openai(server).complete(REQUEST)

    def test_error_bodies_in_other_shapes_are_read(self) -> None:
        import httpx

        server = FakeServer(httpx.Response(422, json={"detail": "model not found"}))
        with pytest.raises(LLMError, match="model not found"):
            openai(server).complete(REQUEST)


class TestMistral:
    def test_images_are_given_as_a_plain_data_url(self) -> None:
        server = FakeServer(ok(openai_answer()))
        client = MistralClient("mistral-medium-latest", api_key="k", transport=server.transport)
        client.complete(REQUEST)
        assert str(server.requests[0].url) == "https://api.mistral.ai/v1/chat/completions"
        image = server.body()["messages"][1]["content"][0]
        assert image == {"type": "image_url", "image_url": f"data:image/png;base64,{B64}"}
        assert client.name == "mistral:mistral-medium-latest"


def anthropic_answer() -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": '{"action":'}, {"type": "text", "text": ' "back"}'}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 50,
            "output_tokens": 9,
            "cache_creation_input_tokens": 1200,
            "cache_read_input_tokens": 0,
        },
    }


class TestAnthropic:
    def test_request_format(self) -> None:
        server = FakeServer(ok(anthropic_answer()))
        AnthropicClient("claude-sonnet-5-5", api_key="sk-ant", transport=server.transport).complete(REQUEST)
        request = server.requests[0]
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert server.body() == {
            "model": "claude-sonnet-5-5",
            "max_tokens": 4096,
            # the system prompt is the same at every turn: cached
            "system": [{"type": "text", "text": "You test web apps.", "cache_control": {"type": "ephemeral"}}],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": B64}},
                        {"type": "text", "text": "Next action?"},
                    ],
                }
            ],
            "temperature": 0.1,
        }

    def test_answer_and_cache_usage(self) -> None:
        server = FakeServer(ok(anthropic_answer()))
        completion = AnthropicClient("claude-x", api_key="k", transport=server.transport).complete(REQUEST)
        assert completion.text == '{"action": "back"}'
        assert completion.usage == TokenUsage(input_tokens=50, output_tokens=9, cache_write_tokens=1200)
        assert completion.model == "claude-x"


def gemini_answer() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "Let me think...", "thought": True},
                        {"text": '{"action": "wait"}'},
                    ],
                }
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 300,
            "candidatesTokenCount": 10,
            "thoughtsTokenCount": 40,
            "cachedContentTokenCount": 100,
        },
    }


class TestGemini:
    def test_request_format(self) -> None:
        server = FakeServer(ok(gemini_answer()))
        GeminiClient("gemini-3.8-flash", api_key="g-key", transport=server.transport).complete(REQUEST)
        request = server.requests[0]
        assert str(request.url) == (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "g-key"
        assert server.body() == {
            "systemInstruction": {"parts": [{"text": "You test web apps."}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inlineData": {"mimeType": "image/png", "data": B64}},
                        {"text": "Next action?"},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }

    def test_thoughts_are_skipped_and_counted_as_output(self) -> None:
        server = FakeServer(ok(gemini_answer()))
        completion = GeminiClient("g", api_key="k", transport=server.transport).complete(REQUEST)
        assert completion.text == '{"action": "wait"}'
        assert completion.usage == TokenUsage(input_tokens=200, output_tokens=50, cache_read_tokens=100)

    def test_a_blocked_prompt_is_an_error(self) -> None:
        server = FakeServer(ok({"promptFeedback": {"blockReason": "SAFETY"}}))
        with pytest.raises(LLMError, match="SAFETY"):
            GeminiClient("g", api_key="k", transport=server.transport).complete(REQUEST)

    def test_options_merge_into_the_generation_config(self) -> None:
        server = FakeServer(ok(gemini_answer()))
        GeminiClient("g", api_key="k", transport=server.transport, options={"generationConfig": {"topK": 1}}).complete(
            REQUEST
        )
        assert server.body()["generationConfig"] == {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "topK": 1,
        }

    def test_unsupported_json_mime_type_is_dropped(self) -> None:
        server = FakeServer(error(400, "response_mime_type is not supported"), ok(gemini_answer()))
        GeminiClient("g", api_key="k", transport=server.transport, sleep=server.sleep).complete(REQUEST)
        assert server.body(1)["generationConfig"] == {"temperature": 0.1}
