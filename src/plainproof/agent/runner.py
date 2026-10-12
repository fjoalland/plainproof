"""The agent loop: observe the page, let the model decide, check the decision, act, repeat.

For each scenario:

1. **Interpret** (one call): the scenario, written in business words, becomes precise steps,
   each an action or a verification, tied to the line it comes from (see ``plan.py``).
2. **Observe**: the browser numbers the interactive elements of the whole page and takes an
   annotated screenshot.
3. **Decide** (one call per action): the model gets the screenshot, the element list, the
   steps, its progress, its notes and a one-line history, and answers with ONE action.
4. **Guard**: the action is checked before it runs (see ``guards.py``): it may be refused
   (a verification is pending, it repeats a success, it scrolls in circles), and a check is
   bound to the expectation of its step.
5. **Act**: the browser performs it on the numbered element, confirmed by its label.
6. **Verify**: a check is made on the page itself; a check described in words is judged by a
   separate call whose quote must really be on the page (see ``judge.py``).
7. **Conclude**: a success is refused when a check failed, a verification is missing or the
   scenario was not carried out to the end. After a failure, one call explains it.

The model only ever sees secrets as ``${PLACEHOLDERS}``; the browser gets the real values.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..browser.driver import BrowserDriver
from ..browser.imaging import highlight_action
from ..browser.model import Observation
from ..i18n import t
from ..llm.base import LLMClient, LLMError
from ..llm.pricing import Price
from ..replay.recorder import Recorder
from ..results import Diagnosis, PlanStep, RunListener, RunResult, SilentListener, Step
from ..scenario import Scenario
from ..secrets import Secrets
from ..text import truthy
from . import guards
from .actions import TARGETED, Outcome, as_ref, banner, check_key
from .calls import ModelAnswerError, ModelCalls
from .diagnosis import diagnosis_request_text, read_diagnosis
from .judge import evaluate_judgement, judge_request_text
from .plan import clean_plan, plan_request_text
from .progress import history_text, numbered, progress_text
from .prompts import agent_prompt, diagnosis_prompt, judge_prompt, plan_prompt

MAX_WAIT_S = 15.0
STALLED_WINDOW = 12


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _first_line(error: BaseException) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


def _url(browser: BrowserDriver) -> str:
    try:
        return browser.url
    except Exception:  # noqa: BLE001 - a closed page has no URL, the report says so
        return ""


def _seconds(value: object) -> float:
    """A duration asked by the model: a finite, positive number of seconds (1 when unreadable)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 1.0
    try:
        seconds = float(value)
    except ValueError:
        return 1.0
    return max(seconds, 0.0) if math.isfinite(seconds) else 1.0


@dataclass
class _Run:
    """Everything one scenario run carries from one turn to the next."""

    scenario: Scenario
    browser: BrowserDriver
    out_dir: Path
    calls: ModelCalls
    result: RunResult
    recorder: Recorder
    lines: list[str]
    """The steps the agent executes: the interpretation, or the scenario lines."""
    plan: list[PlanStep] | None
    step_no: int = 0
    notes: list[str] = field(default_factory=list)
    checked_steps: set[int] = field(default_factory=set)
    failed_checks: dict[tuple[str, bool], int] = field(default_factory=dict)
    model_failed: bool = False

    @property
    def secrets(self) -> Secrets:
        return self.scenario.secrets

    @property
    def total(self) -> int:
        return len(self.lines)

    @property
    def verify_flags(self) -> list[bool] | None:
        return [p.verify for p in self.plan] if self.plan else None

    def needs_check(self, n: int) -> bool:
        return guards.needs_check(self.lines, self.verify_flags, n)

    def source_line(self, n: int) -> str:
        """The scenario line step ``n`` of the plan comes from, as its author wrote it."""
        if not self.plan or not 1 <= n <= len(self.plan):
            return ""
        source = self.plan[n - 1].source
        lines = self.scenario.steps
        return lines[source - 1] if 1 <= source <= len(lines) else ""

    def fail(self, reason: str) -> bool:
        self.result.success, self.result.reason = False, reason
        return True


class Agent:
    """Runs scenarios with a model. One agent can run many scenarios, one after another."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_steps: int = 25,
        interpret: bool = True,
        diagnose: bool = True,
        price: Price | None = None,
        listener: RunListener | None = None,
    ) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.interpret = interpret
        self.diagnose = diagnose
        self.price = price
        self.listener: RunListener = listener or SilentListener()

    # -- a whole run ------------------------------------------------------------------------------
    def run(self, scenario: Scenario, browser: BrowserDriver, out_dir: Path) -> RunResult:
        """Run one scenario in ``browser``; screenshots are written to ``out_dir``."""
        out_dir.mkdir(parents=True, exist_ok=True)
        calls = ModelCalls(self.llm)
        plan = self._interpret(calls, scenario) if self.interpret else None
        result = RunResult(scenario=scenario.source, model=self.llm.name, started_at=_now())
        if plan:
            result.plan = [PlanStep(scenario.secrets.hide(p.text), p.verify, p.absent, p.source) for p in plan]
            self.listener.on_plan(result.plan)
        state = _Run(
            scenario=scenario,
            browser=browser,
            out_dir=out_dir,
            calls=calls,
            result=result,
            recorder=Recorder(scenario.secrets),
            lines=[p.text for p in plan] if plan else scenario.steps,
            plan=plan,
        )
        for index in range(1, self.max_steps + 1):
            if self._turn(state, index):
                break
        else:
            state.fail(t("reason.max_steps", n=self.max_steps))
        final_png = self._final_screenshot(state)
        if self.diagnose and result.success is False and not state.model_failed:
            result.diagnosis = self._explain(state, final_png)
        result.usage = calls.meter.report(self.price)
        result.finished_at = _now()
        if result.success:
            result.recording = state.recorder.data(scenario.name, self.llm.name)
        return result

    def _interpret(self, calls: ModelCalls, scenario: Scenario) -> list[PlanStep] | None:
        """Precise steps from the business wording, or None: the run then executes the lines as written."""
        lines = scenario.steps
        if not lines:
            return None
        try:
            answer = calls.ask(plan_prompt(), plan_request_text(lines, scenario.context), attempts=2)
        except (LLMError, ModelAnswerError):
            return None
        return clean_plan(answer, lines)

    # -- one turn -----------------------------------------------------------------------------------
    def _turn(self, state: _Run, index: int) -> bool:
        """Observe, decide, guard, act. True when the run is over."""
        started = time.monotonic()
        try:
            observation = state.browser.observe()
        except Exception as err:  # noqa: BLE001 - page unreachable or browser gone: end with a report
            return state.fail(t("reason.observe_error", error=_first_line(err)))
        state.recorder.start(observation.url)
        shot = f"step_{index:02d}.png"
        (state.out_dir / shot).write_bytes(observation.annotated_png)
        try:
            action = self._decide(state, observation, steps_left=self.max_steps - index + 1)
        except (LLMError, ModelAnswerError) as err:
            state.model_failed = True
            return state.fail(t("reason.model_error", error=err))

        blocked = self._advance(state, action)
        proof, proof_note = None, ""
        if action.get("action") == "check" and not blocked and state.plan and state.needs_check(state.step_no):
            action, proof, proof_note = guards.bind_check(action, state.plan[state.step_no - 1], state.step_no)
        if action.get("action") == "check" and not blocked and proof is not False:
            state.checked_steps.add(state.step_no)
        note = state.secrets.hide(str(action.get("note") or "").strip())
        if note and note not in state.notes:
            state.notes.append(note)

        shown: dict[str, Any] = state.secrets.redact(action)
        step = Step(
            index=index,
            url=observation.url,
            action=shown,
            thought=str(shown.get("thought", "")),
            screenshot=shot,
            step_no=state.step_no,
            proof=proof,
        )
        step.action_screenshot = f"step_{index:02d}_action.png"
        (state.out_dir / step.action_screenshot).write_bytes(
            highlight_action(observation.screenshot_png, observation.elements, as_ref(action.get("ref")), banner(shown))
        )
        if action.get("action") == "finish":
            self._finish(state, step, action)
            step.url_after = observation.url
            self._close(state, step, started)
            return True

        stop = self._act(state, step, action, observation, blocked, proof, proof_note)
        if stop:
            step.url_after = observation.url
        else:
            state.browser.settle()
            step.url_after = _url(state.browser)
        self._close(state, step, started)
        if stop:
            return True
        steps = state.result.steps
        if guards.stalled_on_step(steps, state.total, STALLED_WINDOW):
            return state.fail(t("reason.stalled", step=state.step_no, total=state.total, n=STALLED_WINDOW))
        if guards.repeated_tail(steps) >= 4 or guards.sterile_tail(steps):
            return state.fail(t("reason.loop", action=banner(step.action)))
        return False

    def _decide(self, state: _Run, observation: Observation, steps_left: int) -> dict[str, Any]:
        history = state.result.steps
        text = history_text(history)
        if guards.scroll_tail(history) >= 2:
            text += (
                "\n\nWARNING: you scrolled twice in a row. Scrolling does not reveal anything new: the element "
                "list already covers the whole page. Click the element you need by its number, or conclude."
            )
        if guards.repeated_tail(history) >= 2:
            following = state.step_no + 1
            text += (
                "\n\nWARNING: you just repeated the same action and got the same result: it changes nothing. "
                + (
                    f'If step {state.step_no} is already done, move on to step {following} ("step": {following}): '
                    f"{state.lines[following - 1]} "
                    if 1 <= state.step_no < state.total
                    else ""
                )
                + "Otherwise change approach (another element, a shorter fragment) or finish with success=false."
            )
        if guards.failed_checks_tail(history) >= 3:
            text += (
                "\n\nWARNING: 3 checks failed in a row. The text is not on this page. Stop trying variants: "
                "either continue with the next scenario step, or finish with success=false explaining what is missing."
            )
        if history and history[-1].error:
            text += (
                f"\n\nLAST ACTION FAILED: {history[-1].error}\n"
                "Do not repeat it as is. Use the information above (available options, valid numbers, "
                "field value) to choose a different element or a different action."
            )
        if steps_left <= 3:
            text += (
                f"\n\nSTEPS LEFT: {steps_left}. Conclude now: finish with success=true only if everything "
                "was done and verified, else success=false."
            )
        progress = progress_text(state.lines, state.step_no, history, state.notes, state.source_line(state.step_no))
        user_text = (
            f"TEST SCENARIO, STEP BY STEP:\n{numbered(state.lines)}\n\n"
            f"PROGRESS:\n{progress}\n\n"
            f"ACTION HISTORY:\n{text}\n\n"
            f"CURRENT PAGE: {observation.url}\nTITLE: {observation.title}\n\n"
            # a secret typed into a plain text field must not come back through its value
            f"INTERACTIVE ELEMENTS ON THIS PAGE:\n{state.secrets.hide(observation.elements_text())}\n\n"
            "What is the next action? Answer with a single JSON object."
        )
        system = agent_prompt(state.scenario.context, self.llm.vision)
        return state.calls.ask(system, user_text, image=observation.annotated_png, attempts=2)

    @staticmethod
    def _advance(state: _Run, action: dict[str, Any]) -> str:
        """Move the step counter as the model claims, within limits. Returns why the action is refused, or ""."""
        claimed = as_ref(action.get("step"))
        if claimed is None:
            return ""
        wanted = max(state.step_no, min(claimed, state.total))
        if state.plan and wanted == state.step_no:
            wanted = guards.realign_step(action, wanted, state.plan, state.result.steps)
        current = state.step_no
        pending = wanted > current >= 1 and current not in state.checked_steps and state.needs_check(current)
        kind = action.get("action")
        if pending and kind not in ("finish", "check", "note"):
            # Refused, NOT executed: the next step's action (a click on another menu) would change
            # the page and make the pending verification impossible.
            return (
                f"Action refused and not executed: it belongs to step {wanted}, but step {current} asks you to "
                f"verify something and no check was run for it. The page is unchanged: run that check now, "
                f'with "step": {current}.'
            )
        if pending and kind == "check":
            return ""  # a check numbered too far ahead counts for the step still waiting for one
        state.step_no = wanted
        return ""

    def _act(
        self,
        state: _Run,
        step: Step,
        action: dict[str, Any],
        observation: Observation,
        blocked: str,
        proof: bool | None,
        proof_note: str,
    ) -> bool:
        """Perform the action unless a guard refuses it. True when the run must stop."""
        if blocked:
            step.error = blocked
            return False
        redundant = guards.already_succeeded(step.action, state.result.steps, state.step_no)
        if redundant is not None:
            step.error = self._redundant(state, redundant)
            return False
        key = check_key(action)
        if key is not None and state.failed_checks.get(key, 0) >= 2:
            # The same check already failed twice: the text is not there, do not hit the page again.
            state.failed_checks[key] += 1
            step.check = False
            step.result = (
                f"CHECK FAILED: {key[0]!r} already failed {state.failed_checks[key] - 1} times. "
                "It is not on this page: move to the next step or finish with success=false."
            )
            return state.failed_checks[key] >= 3 and state.fail(t("reason.check_unsatisfied", check=key[0]))
        if action.get("action") == "scroll" and guards.scroll_tail(state.result.steps) >= 2:
            # Scrolling never reveals a new element (the list is page-wide): this is how agents
            # used to burn their budget going up and down.
            step.error = (
                "Scrolling refused: you already scrolled twice in a row and the element list already "
                "covers the whole page. Click the element you need by its number, or finish with "
                "success=false if it is not listed."
            )
            return False
        # Rows are read before acting: a deletion removes the very row it was clicked in.
        rows = state.browser.row_texts() if action.get("action") in TARGETED else None
        try:
            outcome = self._execute(state, action)
        except Exception as err:  # noqa: BLE001 - the model reads the error and tries another way
            step.error = state.secrets.hide(_first_line(err)[:300])
            return False
        step.result, step.check = state.secrets.hide(outcome.message), outcome.check
        if key is not None and outcome.check is False:
            state.failed_checks[key] = state.failed_checks.get(key, 0) + 1
        if proof is False:
            outcome = self._judge_the_step(state, step, outcome, proof_note)
        state.recorder.add(action, observation, outcome, state.step_no, rows)
        return False

    def _execute(self, state: _Run, action: dict[str, Any]) -> Outcome:
        browser, secrets = state.browser, state.secrets
        kind = action.get("action")
        if kind == "navigate":
            return Outcome(browser.navigate(str(action.get("url", ""))))
        expect = str(action.get("label") or "").strip() or None
        ref = as_ref(action.get("ref"))
        if kind == "click":
            return Outcome(browser.click(ref, expect=expect))
        if kind == "type":
            text = secrets.substitute(str(action.get("text", "")))
            return Outcome(browser.type_text(ref, text, truthy(action.get("submit")), expect=expect))
        if kind == "select":
            return Outcome(browser.select(ref, secrets.substitute(str(action.get("option", ""))), expect=expect))
        if kind == "press":
            return Outcome(browser.press(str(action.get("key") or "Enter")))
        if kind == "scroll":
            return Outcome(browser.scroll(str(action.get("direction") or "down")))
        if kind == "wait":
            return Outcome(browser.wait(min(_seconds(action.get("seconds", 1)), MAX_WAIT_S)))
        if kind == "back":
            return Outcome(browser.go_back())
        if kind == "note":  # the note itself was kept before execution
            return Outcome("Note recorded")
        if kind == "check":
            absent = truthy(action.get("absent"))
            if action.get("meaning"):
                return self._judge(state, str(action["meaning"]), absent)
            if action.get("url"):
                found = browser.check_url(str(action["url"]), absent=absent)
            else:
                found = browser.check_text(str(action.get("text", "")), absent=absent)
            return Outcome(found.message, check=found.ok)
        raise ValueError(f"Unknown action: {kind}")

    def _judge(self, state: _Run, expectation: str, absent: bool) -> Outcome:
        page = state.secrets.hide(state.browser.page_text())
        text = judge_request_text(expectation, absent, _url(state.browser), page)
        answer = state.calls.ask(judge_prompt(), text, attempts=2)
        return evaluate_judgement(answer, expectation, absent, page, state.browser.only_in_typed_fields)

    def _judge_the_step(self, state: _Run, step: Step, outcome: Outcome, proof_note: str) -> Outcome:
        """A check that does not prove its verification step ("List of my reports" for "the reports
        page opens"): judge the step's own wording now, on this same page, rather than hoping the
        model asks for it before moving on."""
        assert state.plan is not None
        spec = state.plan[step.step_no - 1]
        try:
            judged = self._judge(state, spec.text, spec.absent)
        except (LLMError, ModelAnswerError):
            step.result += proof_note
            return outcome
        step.result = state.secrets.hide(f"{judged.message} [judged on the step's wording, after: {step.result}]")
        step.check, step.proof = judged.check, True
        state.checked_steps.add(step.step_no)
        return judged

    @staticmethod
    def _redundant(state: _Run, earlier: Step) -> str:
        following = state.step_no + 1
        return (
            f"Not executed: action {earlier.index} already did exactly this for step {state.step_no} and it "
            "succeeded. Repeating it changes nothing. "
            f"If step {state.step_no} still needs a click or a typing, do it now (a check never clicks). "
            + (
                f'If nothing else is missing, answer with the first action of step {following} ("step": {following}): '
                f"{state.lines[following - 1]}"
                if following <= state.total
                else "If nothing else is missing, this was the last step: finish."
            )
        )

    @staticmethod
    def _finish(state: _Run, step: Step, action: dict[str, Any]) -> None:
        result = state.result
        result.success = truthy(action.get("success"))
        result.reason = state.secrets.hide(str(action.get("reason", "")))
        objection = guards.verdict_objection(state.lines, result.steps, state.verify_flags) if result.success else None
        if objection:
            result.success, result.reason = False, objection
            step.result = t("step.finish_rejected", reason=objection)
        else:
            step.result = t("step.finished")

    def _close(self, state: _Run, step: Step, started: float) -> None:
        step.duration_ms = int((time.monotonic() - started) * 1000)
        state.result.steps.append(step)
        self.listener.on_step(step)

    # -- after the loop -----------------------------------------------------------------------------
    @staticmethod
    def _final_screenshot(state: _Run) -> bytes:
        try:
            png = state.browser.observe().screenshot_png
        except Exception:  # noqa: BLE001 - the report simply has no final screenshot
            return b""
        (state.out_dir / "final.png").write_bytes(png)
        return png

    def _explain(self, state: _Run, final_png: bytes) -> Diagnosis | None:
        """A plain-language explanation of the failure; None when it cannot be had (never fails the run)."""
        image = final_png if final_png and self.llm.vision else None
        text = diagnosis_request_text(state.lines, state.result.steps, state.result.reason)
        try:
            answer = state.calls.ask(diagnosis_prompt(with_screenshot=image is not None), text, image=image, attempts=1)
        except (LLMError, ModelAnswerError):
            return None
        return read_diagnosis(answer, state.secrets)
