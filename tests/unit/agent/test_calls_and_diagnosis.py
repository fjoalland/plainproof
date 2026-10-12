"""Model calls made by the agent (JSON answers, usage, vision) and failure explanations."""

import pytest

from plainproof.agent.calls import ModelAnswerError, ModelCalls
from plainproof.agent.diagnosis import diagnosis_request_text, read_diagnosis
from plainproof.agent.prompts import agent_prompt, diagnosis_prompt, judge_prompt, plan_prompt
from plainproof.i18n import use_language
from plainproof.llm.base import ImagePart, TokenUsage
from plainproof.llm.scripted import ScriptedClient
from plainproof.secrets import Secrets

from .helpers import step


class TestModelCalls:
    def test_returns_the_json_object_and_counts_usage(self) -> None:
        llm = ScriptedClient([{"action": "back"}], usage=TokenUsage(100, 5))
        calls = ModelCalls(llm)
        assert calls.ask("system", "text", image=b"png") == {"action": "back"}
        assert calls.meter.calls == 1
        assert calls.meter.usage == TokenUsage(100, 5)
        assert isinstance(llm.requests[0].messages[0].parts[0], ImagePart)

    def test_an_unreadable_answer_is_asked_again_and_still_billed(self) -> None:
        calls = ModelCalls(ScriptedClient(["sorry, no idea", {"action": "back"}]))
        assert calls.ask("s", "t", attempts=2) == {"action": "back"}
        assert calls.meter.calls == 2

    def test_gives_up_after_the_attempts(self) -> None:
        with pytest.raises(ModelAnswerError, match="no JSON"):
            ModelCalls(ScriptedClient(["nope", "still nope"])).ask("s", "t", attempts=2)

    def test_no_screenshot_for_a_model_without_vision(self) -> None:
        llm = ScriptedClient([{"a": 1}], vision=False)
        ModelCalls(llm).ask("s", "t", image=b"png")
        assert not llm.requests[0].has_images


class TestPrompts:
    def test_agent_prompt_language_context_and_vision(self) -> None:
        with use_language("fr"):
            prompt = agent_prompt("Log in with ${APP_USER}.", vision=True)
        assert 'Write "thought" and "reason" in French' in prompt
        assert prompt.endswith(
            "Trust it for how to log in, the vocabulary and the known behaviour of the screens:\n"
            "Log in with ${APP_USER}."
        )
        assert "a screenshot where every interactive element carries a red number" in prompt
        blind = agent_prompt(vision=False)
        assert "screenshot" not in blind
        assert "APPLICATION CONTEXT, written" not in blind

    def test_other_prompts_follow_the_language(self) -> None:
        with use_language("fr"):
            assert 'Write "text" in French' in plan_prompt()
            assert "one short sentence in French" in judge_prompt()
            assert 'Write "summary" and "details" in French' in diagnosis_prompt()
        assert "and no screenshot." in diagnosis_prompt(with_screenshot=False)


class TestDiagnosis:
    def test_request_text(self) -> None:
        history = [step(1, {"action": "click", "ref": 2}, result="Clicked [2]", step_no=1)]
        text = diagnosis_request_text(["Click Save.", "I see Saved."], history, "Success verdict refused")
        assert text.startswith("TEST SCENARIO:\n1. Click Save.\n2. I see Saved.\n\nACTION HISTORY:\n1. [step 1] click")
        assert "RUN STOPPED BECAUSE: Success verdict refused" in text

    def test_answer_is_normalised_and_redacted(self) -> None:
        secrets = Secrets({"APP_PASSWORD": "s3cret!"})
        answer = {"summary": "Typed s3cret! then failed.", "cause": "Environment", "details": "x"}
        diagnosis = read_diagnosis(answer, secrets)
        assert diagnosis is not None
        assert diagnosis.summary == "Typed ${APP_PASSWORD} then failed."
        assert diagnosis.cause == "environment"
        assert read_diagnosis({"summary": ""}, secrets) is None
        assert read_diagnosis(["not", "a", "dict"], secrets) is None
