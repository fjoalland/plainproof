"""The agent loop, end to end, with a scripted model and a fake browser (no network, no Chromium).

Reproduced here: the loops and the false successes seen on real application suites. Each
guard is exercised through the loop, the way a real model trips it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plainproof.agent.runner import Agent
from plainproof.browser.model import Element
from plainproof.i18n import use_language
from plainproof.llm.base import ChatRequest, Completion, LLMError
from plainproof.llm.pricing import Price
from plainproof.llm.scripted import ScriptedClient
from plainproof.results import PlanStep, RunResult, Step
from plainproof.scenario import Scenario
from plainproof.secrets import Secrets
from tests.fakes import FakeBrowser


def make_agent(script: list[Any], **options: Any) -> tuple[Agent, ScriptedClient]:
    vision = options.pop("vision", True)
    llm = ScriptedClient(script, vision=vision, repeat_last=options.pop("repeat_last", False))
    options.setdefault("interpret", False)
    options.setdefault("diagnose", False)
    return Agent(llm, **options), llm


def scenario(text: str, *, secrets: Secrets | None = None, context: str = "") -> Scenario:
    return Scenario(name="s", source=text, text=text, secrets=secrets or Secrets(), context=context)


def run(agent: Agent, text: str, tmp_path: Path, browser: FakeBrowser | None = None, **kw: Any) -> RunResult:
    return agent.run(scenario(text, **kw), browser or FakeBrowser(), tmp_path / "run")


def finish(success: bool = False, step: int = 1) -> dict[str, Any]:
    return {"step": step, "action": "finish", "success": success, "reason": "done" if success else "stop"}


# -- the basic loop -----------------------------------------------------------------------
def test_a_passing_run(tmp_path: Path) -> None:
    agent, llm = make_agent(
        [
            {"step": 1, "thought": "open", "action": "click", "ref": 1, "label": "Login"},
            {"step": 1, "thought": "verify", "action": "check", "text": "Welcome"},
            finish(True),
        ],
        price=Price(1.0, 10.0),
    )
    browser = FakeBrowser(elements=[Element(ref=1, tag="button", text="Login")])
    result = run(agent, "Click Login and check that Welcome is shown", tmp_path, browser)
    assert result.success is True, result.reason
    assert [s.kind for s in result.steps] == ["click", "check", "finish"]
    assert result.steps[1].check is True
    assert result.steps[2].result == "Test finished"
    assert result.model == "scripted:test"
    assert result.started_at
    assert result.finished_at
    out = tmp_path / "run"
    assert {"step_01.png", "step_01_action.png", "final.png"} <= {p.name for p in out.iterdir()}
    assert result.steps[0].screenshot == "step_01.png", "file names only: reports must not leak paths"
    assert result.usage is not None
    assert result.usage.calls == 3
    assert result.usage.cost_usd is not None
    first = llm.requests[0]
    assert first.has_images
    assert '[1] <button> text="Login"' in llm.user_texts()[0]


def test_every_step_is_reported_to_the_listener(tmp_path: Path) -> None:
    seen: list[Step] = []

    class Listener:
        def on_plan(self, plan: list[PlanStep]) -> None:
            raise AssertionError("no plan without interpretation")

        def on_step(self, step: Step) -> None:
            seen.append(step)

    agent, _ = make_agent([{"step": 1, "action": "click", "ref": 1}, finish()], listener=Listener())
    result = run(agent, "Click", tmp_path)
    assert seen == result.steps


def test_an_action_error_is_recorded_and_explained_to_the_model(tmp_path: Path) -> None:
    class Broken(FakeBrowser):
        def select(self, ref: int | None, option: str, expect: str | None = None) -> str:
            raise ValueError('Option "X" is not in the open list. Available options: ["A", "B"]')

    agent, llm = make_agent([{"step": 1, "action": "select", "ref": 1, "option": "X"}, finish()])
    result = run(agent, "Choose X", tmp_path, Broken())
    assert result.steps[0].error
    assert "Available options" in result.steps[0].error
    assert "LAST ACTION FAILED" in llm.user_texts()[1]
    assert "Available options" in llm.user_texts()[1]


def test_the_budget_is_announced_then_enforced(tmp_path: Path) -> None:
    agent, llm = make_agent([{"step": 1, "action": "check", "text": f"nope{i}"} for i in range(5)], max_steps=5)
    result = run(agent, "Check things", tmp_path)
    texts = llm.user_texts()
    assert "STEPS LEFT: 3" in texts[2]
    assert "STEPS LEFT: 1" in texts[4]
    assert "3 checks failed in a row" in texts[3]
    assert result.success is False
    assert result.reason == "Maximum number of actions reached (5) without a verdict."


def test_a_model_error_stops_the_run_cleanly(tmp_path: Path) -> None:
    class Down(ScriptedClient):
        def complete(self, request: ChatRequest) -> Completion:
            raise LLMError("anthropic:claude: HTTP 529: overloaded", transient=True)

    agent = Agent(Down([]), interpret=False, diagnose=True)
    result = agent.run(scenario("Click"), FakeBrowser(), tmp_path / "run")
    assert result.success is False
    assert result.reason.startswith("Model error: ")
    assert result.diagnosis is None, "no explanation is asked from a model that just failed"


def test_an_unreadable_answer_is_asked_again(tmp_path: Path) -> None:
    agent, _ = make_agent(["I think I will click", finish()])
    assert run(agent, "Click", tmp_path).reason == "stop"


def test_a_page_that_cannot_be_observed_stops_the_run(tmp_path: Path) -> None:
    browser = FakeBrowser()
    browser.observe_error = RuntimeError("Target page, context or browser has been closed\nmore")
    agent, _ = make_agent([])
    result = run(agent, "Click", tmp_path, browser)
    assert result.reason == "Could not observe the page: Target page, context or browser has been closed"


def test_a_finish_success_given_as_text_false_is_a_failure(tmp_path: Path) -> None:
    agent, _ = make_agent([{"step": 1, "action": "finish", "success": "false", "reason": "nope"}])
    assert run(agent, "Click", tmp_path).success is False


def test_waits_are_capped(tmp_path: Path) -> None:
    agent, _ = make_agent([{"step": 1, "action": "wait", "seconds": 600}, finish()])
    browser = FakeBrowser()
    run(agent, "Wait", tmp_path, browser)
    assert browser.calls == [("wait", 15.0)]


# -- verdict guard ----------------------------------------------------------------------------
def test_success_is_refused_after_a_failed_last_check(tmp_path: Path) -> None:
    agent, _ = make_agent(
        [
            {"step": 1, "action": "check", "text": "Welcome"},
            {"step": 1, "action": "check", "text": "Goodbye"},
            finish(True),
        ]
    )
    result = run(agent, "Verify that Goodbye is shown", tmp_path)
    assert result.success is False
    assert 'FAILED ("Goodbye")' in result.reason
    assert result.steps[-1].result.startswith("Verdict overridden")


def test_success_is_refused_when_nothing_was_verified(tmp_path: Path) -> None:
    agent, _ = make_agent([{"step": 1, "action": "click", "ref": 1}, finish(True)])
    result = run(agent, "Click Save then verify that the message appears", tmp_path)
    assert result.success is False
    assert "no check was made" in result.reason


def test_success_is_accepted_when_the_last_check_passed(tmp_path: Path) -> None:
    agent, _ = make_agent(
        [
            {"step": 1, "action": "check", "text": "Missing"},
            {"step": 1, "action": "check", "text": "Welcome"},
            finish(True),
        ]
    )
    assert run(agent, "Verify that Welcome is shown", tmp_path).success is True


def test_an_absence_check(tmp_path: Path) -> None:
    agent, _ = make_agent([{"step": 1, "action": "check", "text": "Error", "absent": True}, finish(True)])
    result = run(agent, "Verify that no error is shown", tmp_path)
    assert result.success is True
    assert result.steps[0].result == 'CHECK OK: "Error" is absent from the page'


# -- secrets ----------------------------------------------------------------------------------
def test_a_secret_is_typed_for_real_but_never_shown(tmp_path: Path) -> None:
    secrets = Secrets({"APP_PASSWORD": "s3cret!"})
    agent, llm = make_agent(
        [{"step": 1, "action": "type", "ref": 2, "text": "${APP_PASSWORD}"}, finish()], diagnose=True, repeat_last=True
    )
    browser = FakeBrowser()
    result = run(agent, "Type ${APP_PASSWORD}", tmp_path, browser, secrets=secrets)
    assert browser.calls == [("type", 2, "s3cret!")], "the page gets the real value"
    assert result.steps[0].result == 'Typed "${APP_PASSWORD}" into [2]', "history and report never do"
    assert all("s3cret!" not in text for text in llm.user_texts())
    assert "s3cret!" not in str(result.to_dict())


# -- loops ------------------------------------------------------------------------------------
def test_an_identical_failed_check_is_not_run_a_third_time(tmp_path: Path) -> None:
    agent, llm = make_agent([{"step": 1, "action": "check", "text": "Nope"}] * 6)
    browser = FakeBrowser()
    result = run(agent, "Verify Nope", tmp_path, browser)
    assert [c for c in browser.calls if c[0] == "check"] == [("check", "Nope", False)] * 2
    assert len(result.steps) == 3
    assert "already failed" in result.steps[2].result
    assert result.success is False
    assert "never satisfied" in result.reason
    assert "WARNING" in llm.user_texts()[2]


def test_scrolling_back_and_forth_is_refused_then_stopped(tmp_path: Path) -> None:
    agent, _ = make_agent([{"step": 1, "action": "scroll", "direction": "down"}] * 8)
    browser = FakeBrowser()
    result = run(agent, "Scroll forever", tmp_path, browser)
    assert browser.calls == [("scroll", "down")] * 2, "the third scroll in a row is refused"
    assert result.steps[2].error
    assert "Scrolling refused" in result.steps[2].error
    assert result.success is False
    assert "Loop detected" in result.reason
    assert len(result.steps) == 6


def test_a_sterile_oscillation_is_cut_short(tmp_path: Path) -> None:
    script = [{"step": 1, "action": "scroll" if i % 3 else "wait", "direction": "up", "seconds": 0} for i in range(20)]
    agent, _ = make_agent(script, max_steps=20)
    result = run(agent, "Find the field", tmp_path)
    assert result.success is False
    assert len(result.steps) < 20


def test_a_toggle_clicked_open_and_closed_is_not_a_loop(tmp_path: Path) -> None:
    class Toggle(FakeBrowser):
        open = False

        def click(self, ref: int | None, expect: str | None = None) -> str:
            self.open = not self.open
            return f"Clicked [{ref}] (submenu now {'open' if self.open else 'closed'})"

    agent, _ = make_agent([{"step": 1, "action": "click", "ref": 1}] * 7 + [finish()])
    result = run(agent, "Click", tmp_path, Toggle())
    assert "Loop detected" not in result.reason
    assert len(result.steps) == 8


def test_circling_one_step_ends_the_run(tmp_path: Path) -> None:
    script = [{"step": 1, "action": "click", "ref": i} for i in range(1, 20)]
    agent, _ = make_agent(script, max_steps=20)
    result = run(agent, "Open the menu.\nClick Export.", tmp_path)
    assert result.reason == "Stuck on step 1 of 2: 12 actions without moving past it."


# -- progress ---------------------------------------------------------------------------------
SCENARIO = "Log in.\nClick Reports.\nVerify that the page shows Exports."


def test_progress_tells_the_model_which_step_to_work_on(tmp_path: Path) -> None:
    agent, llm = make_agent(
        [{"step": 1, "action": "click", "ref": 1}, {"step": 2, "action": "click", "ref": 2}, finish(step=3)]
    )
    run(agent, SCENARIO, tmp_path)
    texts = llm.user_texts()
    assert "No step done yet. Start with step 1 of 3" in texts[0]
    assert "CURRENT STEP 1 of 3: Log in." in texts[1]
    assert "Actions already made for step 1: click ref=1" in texts[1]
    assert "Steps 1 to 1 of 3 are done" in texts[2]
    assert "CURRENT STEP 2 of 3" in texts[2]


def test_the_action_of_the_next_step_waits_for_the_pending_check(tmp_path: Path) -> None:
    # "Click Team and verify X": the model clicked Team, then the next step's menu. The click ran,
    # the page changed, and the check of X could only fail afterwards. Now it is refused, not run.
    text = "Log in.\nClick Team and verify that the page shows Members.\nClick Settings."
    agent, _ = make_agent(
        [
            {"step": 1, "action": "click", "ref": 1},
            {"step": 2, "action": "click", "ref": 2},
            {"step": 3, "action": "click", "ref": 3},
            {"step": 2, "action": "check", "text": "Members"},
            {"step": 3, "action": "click", "ref": 3},
            finish(step=3),
        ]
    )
    browser = FakeBrowser(text="Members")
    result = run(agent, text, tmp_path, browser)
    assert browser.calls == [("click", 1), ("click", 2), ("check", "Members", False), ("click", 3)]
    assert result.steps[2].error
    assert "not executed" in result.steps[2].error
    assert result.steps[2].step_no == 2
    assert result.steps[4].step_no == 3


def test_a_successful_check_is_not_repeated_and_the_next_step_is_handed_over(tmp_path: Path) -> None:
    text = "Log in.\nClick Exports and verify that the page shows Reports.\nClick Reports."
    agent, _ = make_agent(
        [
            {"step": 1, "action": "click", "ref": 1},
            {"step": 2, "action": "click", "ref": 2},
            {"step": 2, "action": "check", "text": "Reports"},
            {"step": 2, "action": "check", "text": "Reports", "label": "other"},
            {"step": 3, "action": "click", "ref": 3},
            finish(step=3),
        ]
    )
    browser = FakeBrowser(text="Reports")
    result = run(agent, text, tmp_path, browser)
    assert browser.calls.count(("check", "Reports", False)) == 1
    assert "already did exactly this" in (result.steps[3].error or "")
    assert '"step": 3' in (result.steps[3].error or "")
    assert "Click Reports." in (result.steps[3].error or "")


def test_a_second_click_is_always_executed(tmp_path: Path) -> None:
    agent, _ = make_agent([{"step": 1, "action": "click", "ref": 1}] * 2 + [finish()])
    browser = FakeBrowser()
    run(agent, SCENARIO, tmp_path, browser)
    assert browser.calls == [("click", 1), ("click", 1)]


def test_progress_never_goes_backwards(tmp_path: Path) -> None:
    agent, llm = make_agent(
        [{"step": 3, "action": "click", "ref": 1}, {"step": 1, "action": "click", "ref": 2}, finish(step=3)]
    )
    run(agent, SCENARIO, tmp_path)
    assert "CURRENT STEP 3 of 3" in llm.user_texts()[-1]


def test_notes_survive_every_turn_once(tmp_path: Path) -> None:
    agent, llm = make_agent(
        [
            {"step": 1, "action": "click", "ref": 1, "note": "customer = Jane DOE"},
            {"step": 2, "action": "note", "note": "customer = Jane DOE"},
            finish(step=3),
        ]
    )
    browser = FakeBrowser()
    result = run(agent, SCENARIO, tmp_path, browser)
    assert llm.user_texts()[-1].count("customer = Jane DOE") == 1
    assert result.steps[1].result == "Note recorded"
    assert browser.calls == [("click", 1)]


def test_nothing_is_carried_from_one_scenario_to_the_next(tmp_path: Path) -> None:
    agent, llm = make_agent(
        [
            {"step": 2, "action": "click", "ref": 1, "note": "old fact"},
            finish(step=3),
            finish(step=1),
        ]
    )
    run(agent, SCENARIO, tmp_path)
    run(agent, SCENARIO, tmp_path)
    assert "old fact" not in llm.user_texts()[-1]
    assert "No step done yet" in llm.user_texts()[-1]


# -- interpretation of business wording -------------------------------------------------------
BUSINESS = "I go to Orders.\nI delete the order of 01/12/2050, it must no longer appear."
PLAN = {
    "steps": [
        {"text": "Log in with ${APP_USER}", "verify": False, "source": 0},
        {"text": "Click Orders", "verify": False, "source": 1},
        {"text": "Delete the order of 01/12/2050 and confirm", "verify": False, "source": 2},
        {"text": "The order of 01/12/2050 no longer appears", "verify": True, "absent": True, "source": 2},
    ]
}


def test_the_agent_executes_the_interpreted_steps(tmp_path: Path) -> None:
    plans: list[list[PlanStep]] = []

    class Listener:
        def on_plan(self, plan: list[PlanStep]) -> None:
            plans.append(plan)

        def on_step(self, step: Step) -> None:
            pass

    agent, llm = make_agent([PLAN, finish()], interpret=True, listener=Listener())
    result = run(agent, BUSINESS, tmp_path, context="Log in: user field, password field.")
    assert result.scenario == BUSINESS, "the report keeps what the business user wrote"
    assert result.plan is not None
    assert [s.source for s in result.plan] == [0, 1, 2, 2]
    assert plans == [result.plan]
    interpretation = llm.user_texts()[0]
    assert "1. I go to Orders." in interpretation
    assert "Log in: user field, password field." in interpretation
    assert "1. Log in with ${APP_USER}\n2. Click Orders" in llm.user_texts()[1]
    assert "APPLICATION CONTEXT, written by the team" in llm.requests[1].system


def test_verifications_come_from_the_interpretation_not_from_keywords(tmp_path: Path) -> None:
    agent, _ = make_agent(
        [PLAN] + [{"step": n, "action": "click", "ref": n} for n in (1, 2, 3)] + [finish(True, 4)], interpret=True
    )
    result = run(agent, BUSINESS, tmp_path)
    assert result.success is False
    assert "verif" in result.reason


def test_an_unusable_interpretation_falls_back_to_the_lines(tmp_path: Path) -> None:
    agent, llm = make_agent([{"nope": 1}, {"nope": 2}, finish()], interpret=True)
    result = run(agent, BUSINESS, tmp_path)
    assert result.plan is None
    assert "1. I go to Orders." in llm.user_texts()[2]


def test_a_meaning_check_is_judged_by_a_separate_call(tmp_path: Path) -> None:
    agent, llm = make_agent(
        [
            {"step": 1, "action": "check", "meaning": "a success message"},
            {"satisfied": False, "evidence": "", "explanation": "no message at all"},
            finish(),
        ]
    )
    result = run(agent, "I should see a success message.", tmp_path, FakeBrowser(text="Form"))
    assert result.steps[0].result.startswith("CHECK FAILED (by meaning)")
    assert "no message at all" in result.steps[0].result
    assert result.steps[0].check is False
    assert llm.user_texts()[1].startswith("EXPECTED RESULT: a success message")


DATES_PLAN = {
    "steps": [
        {"text": "Click Create the campaign", "verify": False, "source": 1},
        {"text": "A message says that the end date must be after the start date", "verify": True, "source": 2},
    ]
}


def test_a_weaker_expectation_cannot_turn_a_failed_verification_green(tmp_path: Path) -> None:
    # Real run: the date message was missing (a known defect). The judge refused it twice, then the
    # agent asked "an error message is shown" and declared success.
    agent, _ = make_agent(
        [
            DATES_PLAN,
            {"step": 1, "action": "click", "ref": 1},
            {"step": 2, "action": "check", "meaning": "the end date must be after the start date"},
            {"satisfied": False, "evidence": "", "explanation": "only a generic error"},
            {"step": 2, "action": "check", "meaning": "an error message is shown"},
            {"satisfied": False, "evidence": "", "explanation": "still not the date message"},
            {"step": 2, "action": "check", "text": "error"},
            {"satisfied": False, "evidence": "", "explanation": "generic error only"},
            finish(True, 2),
        ],
        interpret=True,
    )
    page = FakeBrowser(text="An error occurred while creating the campaign")
    result = run(agent, "I validate.\nA message says that the end date must be after the start.", tmp_path, page)
    judged = [s.action.get("meaning") for s in result.steps if s.action.get("meaning")]
    assert judged
    assert all(m == DATES_PLAN["steps"][1]["text"] for m in judged), "the step's own wording, always"
    vague = next(s for s in result.steps if s.action.get("text") == "error")
    assert vague.proof is True
    assert vague.result.startswith("CHECK FAILED (by meaning)")
    assert 'after: CHECK OK: "error"' in vague.result
    assert result.success is False


def test_a_check_on_an_exact_value_proves_the_step_with_the_plan_polarity(tmp_path: Path) -> None:
    plan = {
        "steps": [
            {"text": "Delete the order of 01/12/2050", "verify": False, "source": 1},
            {"text": "The order of 01/12/2050 no longer appears", "verify": True, "absent": True, "source": 1},
        ]
    }
    agent, _ = make_agent(
        [
            plan,
            {"step": 1, "action": "click", "ref": 1},
            {"step": 2, "action": "check", "text": "01/12/2050"},
            finish(True, 2),
        ],
        interpret=True,
    )
    result = run(
        agent, "I delete the order of 01/12/2050, it must no longer appear.", tmp_path, FakeBrowser(text="Orders")
    )
    assert result.steps[1].proof is True
    assert result.steps[1].action["absent"] is True
    assert result.success is True, result.reason


def test_the_author_sentence_stays_in_front_of_the_agent(tmp_path: Path) -> None:
    # The interpretation dropped "(even if the field refuses, I do not retry)" and the agent
    # retyped another date until the form accepted it: the test no longer tested anything.
    plan = {
        "steps": [
            {"text": "Type 31/12/2050 into Start date", "verify": False, "source": 1},
            {"text": "Type 01/01/2050 into End date", "verify": False, "source": 1},
        ]
    }
    agent, llm = make_agent(
        [plan, {"step": 1, "action": "click", "ref": 1}, {"step": 2, "action": "click", "ref": 2}, finish(step=2)],
        interpret=True,
    )
    line = "I put 31/12/2050 as start, then 01/01/2050 as end (even if the field refuses, I do not retry)."
    run(agent, line, tmp_path)
    assert f'written by the scenario author as: "{line}"' in llm.user_texts()[-1]
    assert "NEVER change a value given by the scenario" in llm.requests[-1].system


def test_an_action_on_the_next_step_target_counts_for_that_step(tmp_path: Path) -> None:
    plan = {
        "steps": [
            {"text": 'Click the radio button "Yes"', "verify": False, "source": 1},
            {"text": 'Click "Create the subscription"', "verify": False, "source": 1},
            {"text": "The application refuses: this status already has one", "verify": True, "source": 2},
        ]
    }
    agent, _ = make_agent(
        [
            plan,
            {"step": 1, "action": "click", "ref": 1, "label": "Yes"},
            {"step": 1, "action": "click", "ref": 2, "label": "Create the subscription"},
            finish(step=2),
        ],
        interpret=True,
    )
    result = run(agent, "Yes, then I create.\nIt is refused.", tmp_path)
    assert [s.step_no for s in result.steps[:2]] == [1, 2]


def test_a_check_that_does_not_prove_its_step_is_followed_by_a_judgement_of_the_step(tmp_path: Path) -> None:
    # "List of my reports" was checked for "the reports page opens": the run ended refused for a
    # verification never made. Now the step's own wording is judged right away, on the same page.
    plan = {
        "steps": [
            {"text": 'Click "My reports"', "verify": False, "source": 1},
            {"text": "The reports page opens", "verify": True, "source": 1},
        ]
    }
    agent, _ = make_agent(
        [
            plan,
            {"step": 1, "action": "click", "ref": 1, "label": "My reports"},
            {"step": 2, "action": "check", "text": "List of my reports"},
            {"satisfied": True, "evidence": "List of my reports", "explanation": "the page title"},
            finish(True, 2),
        ],
        interpret=True,
    )
    result = run(agent, "I open my reports: the page opens.", tmp_path, FakeBrowser(text="List of my reports"))
    assert result.steps[1].proof is True
    assert result.steps[1].result.startswith("CHECK OK (by meaning)")
    assert result.success is True, result.reason


# -- failure explanation, recording, vision, language ----------------------------------------
def test_a_failure_is_explained_with_the_final_screenshot(tmp_path: Path) -> None:
    agent, llm = make_agent(
        [finish(), {"summary": "The order was never created.", "cause": "application", "details": "step 1"}],
        diagnose=True,
    )
    result = run(agent, "Create an order", tmp_path)
    assert result.diagnosis is not None
    assert result.diagnosis.cause == "application"
    assert llm.requests[-1].has_images
    assert llm.user_texts()[-1].startswith("TEST SCENARIO:")


def test_a_failed_explanation_never_breaks_the_run(tmp_path: Path) -> None:
    agent, _ = make_agent([finish()], diagnose=True)  # no answer left for the explanation
    result = run(agent, "Create an order", tmp_path)
    assert result.success is False
    assert result.diagnosis is None


def test_a_passing_run_carries_its_recording(tmp_path: Path) -> None:
    agent, _ = make_agent([{"step": 1, "action": "check", "text": "Welcome"}, finish(True)])
    result = run(agent, "Verify Welcome", tmp_path)
    assert result.recording is not None
    assert result.recording["start_url"] == "http://app/#/home"
    assert [s["action"] for s in result.recording["steps"]] == ["check"]
    failing, _ = make_agent([finish()])
    assert run(failing, "Verify Welcome", tmp_path).recording is None


def test_a_model_without_vision_gets_no_screenshot(tmp_path: Path) -> None:
    agent, llm = make_agent([finish()], vision=False)
    run(agent, "Click", tmp_path)
    assert not llm.requests[0].has_images
    assert "screenshot" not in llm.requests[0].system


def test_the_model_writes_in_the_report_language(tmp_path: Path) -> None:
    agent, llm = make_agent([finish()])
    with use_language("fr"):
        result = run(agent, "Click", tmp_path)
    assert 'Write "thought" and "reason" in French' in llm.requests[0].system
    assert result.reason == "stop"


@pytest.mark.parametrize("answer", [{"step": 1, "action": "fly"}, {"step": 1}])
def test_an_unknown_action_is_an_error_the_model_can_read(tmp_path: Path, answer: dict[str, Any]) -> None:
    agent, _ = make_agent([answer, finish()])
    result = run(agent, "Click", tmp_path)
    assert result.steps[0].error
    assert "Unknown action" in result.steps[0].error


def test_checks_by_url_and_navigation(tmp_path: Path) -> None:
    agent, _ = make_agent(
        [
            {"step": 1, "action": "navigate", "url": "http://app/#/orders"},
            {"step": 1, "action": "check", "url": "/orders"},
            {"step": 1, "action": "press", "key": "Escape"},
            {"step": 1, "action": "back"},
            finish(True),
        ]
    )
    result = run(agent, "Open the orders and verify the address", tmp_path)
    assert result.steps[1].check is True
    assert result.success is True
