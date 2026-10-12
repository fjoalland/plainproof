"""Provider-neutral request/answer types and the tolerant JSON reading of model answers."""

import pytest

from plainproof.llm.base import ChatRequest, ImagePart, LLMError, Message, TextPart, TokenUsage
from plainproof.llm.json_answer import parse_json_object


class TestParseJsonObject:
    def test_plain_json(self) -> None:
        assert parse_json_object('{"action": "click", "ref": 3}') == {"action": "click", "ref": 3}

    def test_fenced_json(self) -> None:
        raw = 'Here you go:\n```json\n{"action": "finish", "success": true}\n```'
        assert parse_json_object(raw) == {"action": "finish", "success": True}

    def test_json_inside_prose(self) -> None:
        assert parse_json_object('Sure. {"action": "press", "key": "Enter"} Done.')["key"] == "Enter"

    def test_reasoning_blocks_of_local_models_are_ignored(self) -> None:
        raw = '<think>The user wants {"action": "scroll"}... no.</think>\n{"action": "click", "ref": 1}'
        assert parse_json_object(raw) == {"action": "click", "ref": 1}

    def test_a_list_holding_one_object(self) -> None:
        assert parse_json_object('[{"action": "back"}]') == {"action": "back"}

    @pytest.mark.parametrize("raw", ["I don't know", "", "[1, 2]", '"text"', "{broken"])
    def test_no_object_is_an_error(self, raw: str) -> None:
        with pytest.raises(ValueError, match="JSON"):
            parse_json_object(raw)


class TestTokenUsage:
    def test_sum(self) -> None:
        total = TokenUsage(10, 2, cache_read_tokens=5) + TokenUsage(1, 1, cache_write_tokens=3)
        assert total == TokenUsage(11, 3, cache_read_tokens=5, cache_write_tokens=3)

    def test_total_input_counts_cached_tokens(self) -> None:
        assert TokenUsage(10, 2, cache_read_tokens=5, cache_write_tokens=1).total_input_tokens == 16


def test_request_helpers() -> None:
    request = ChatRequest.single(system="Be brief.", text="Hi", image=b"png")
    assert request.messages == (Message(role="user", parts=(ImagePart(b"png"), TextPart("Hi"))),)
    assert request.has_images
    assert not ChatRequest.single(system="s", text="t").has_images


def test_llm_error_carries_transience() -> None:
    assert LLMError("busy", transient=True).transient
    assert not LLMError("bad key").transient
