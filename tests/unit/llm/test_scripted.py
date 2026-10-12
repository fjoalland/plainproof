"""The scripted model: answers in order, for tests and offline demos."""

from pathlib import Path

import pytest

from plainproof.errors import ConfigError
from plainproof.llm.base import ChatRequest, LLMError
from plainproof.llm.scripted import ScriptedClient

REQUEST = ChatRequest.single(system="s", text="What next?", image=b"png")


def test_answers_in_order_and_records_requests() -> None:
    client = ScriptedClient([{"action": "back"}, "raw text"])
    assert client.complete(REQUEST).text == '{"action": "back"}'
    assert client.remaining == 1
    assert client.complete(REQUEST).text == "raw text"
    assert client.user_texts() == ["What next?", "What next?"]


def test_an_exhausted_script_is_an_error_unless_the_last_answer_repeats() -> None:
    with pytest.raises(LLMError, match="no answer left"):
        ScriptedClient([]).complete(REQUEST)
    looping = ScriptedClient(["a", "b"], repeat_last=True)
    assert [looping.complete(REQUEST).text for _ in range(3)] == ["a", "b", "b"]


def test_from_file(tmp_path: Path) -> None:
    good = tmp_path / "answers.json"
    good.write_text('[{"action": "finish"}]', encoding="utf-8")
    assert ScriptedClient.from_file(good).name == "scripted:answers.json"
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(ConfigError, match="list"):
        ScriptedClient.from_file(bad)
    with pytest.raises(ConfigError, match="Cannot read"):
        ScriptedClient.from_file(tmp_path / "missing.json")
