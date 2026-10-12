"""Replaying a recording without any model.

The actions are played back with plainproof's own browser driver, so dropdowns, dates and
overlays get the same help as in the recorded run, and the same report is written. Before a
checkbox or radio button is clicked, its state is compared with the recording: data that
changed since then is never modified blindly.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agent.actions import TARGETED, Outcome
from ..browser.driver import BrowserDriver
from ..browser.imaging import highlight_action
from ..browser.model import CheckResult, Element, Observation
from ..i18n import t
from ..results import RunListener, RunResult, SilentListener, Step
from ..scenario import Scenario
from ..secrets import Secrets
from ..text import normalize, truthy
from .targets import find_target, target_name

REPLAY_MODEL = "replay"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _first_line(error: BaseException) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


class Replayer:
    """Plays a recording back; same interface as the agent: ``run(scenario, browser, out_dir)``."""

    def __init__(
        self,
        recording: Mapping[str, Any],
        *,
        listener: RunListener | None = None,
        find_attempts: int = 10,
        check_attempts: int = 6,
        pause_s: float = 0.7,
    ) -> None:
        self.recording = recording
        self.listener: RunListener = listener or SilentListener()
        self.find_attempts = max(1, find_attempts)
        self.check_attempts = max(1, check_attempts)
        self.pause_s = pause_s

    def run(self, scenario: Scenario, browser: BrowserDriver, out_dir: Path) -> RunResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        secrets = scenario.secrets
        result = RunResult(scenario=scenario.source, model=REPLAY_MODEL, started_at=_now())
        for index, entry in enumerate(self.recording.get("steps", []), 1):
            started = time.monotonic()
            target = entry.get("target")
            shown: dict[str, Any] = secrets.redact({k: v for k, v in entry.items() if k != "target"})
            if target:
                shown["label"] = target_name(target)
            try:
                observation, element = self._observe(browser, target)
            except Exception as err:  # noqa: BLE001 - page unreachable or browser gone: end with a report
                result.success, result.reason = False, t("reason.observe_error", error=_first_line(err))
                break
            step = Step(
                index=index,
                url=observation.url,
                action=shown,
                thought=t("replay.thought"),
                screenshot=f"step_{index:02d}.png",
                step_no=int(entry.get("step_no", 0)),
            )
            (out_dir / step.screenshot).write_bytes(observation.annotated_png)
            step.action_screenshot = f"step_{index:02d}_action.png"
            highlighted = highlight_action(
                observation.screenshot_png,
                observation.elements,
                element.ref if element else None,
                str(entry.get("action", "")).upper(),
            )
            (out_dir / step.action_screenshot).write_bytes(highlighted)
            try:
                outcome = self._execute(browser, entry, element, secrets)
                step.result, step.check = secrets.hide(outcome.message), outcome.check
            except Exception as err:  # noqa: BLE001 - reported as the reason the replay stopped
                step.error = secrets.hide(_first_line(err)[:300])
            browser.settle()
            step.url_after = browser.url
            step.duration_ms = int((time.monotonic() - started) * 1000)
            result.steps.append(step)
            self.listener.on_step(step)
            if step.error or step.check is False:
                result.success, result.reason = False, t("replay.failed", n=index, why=step.outcome)
                break
        else:
            result.success = True
            result.reason = t("replay.done", n=len(result.steps), date=self.recording.get("recorded_at", "?"))
        with contextlib.suppress(Exception):  # the report simply has no final screenshot
            (out_dir / "final.png").write_bytes(browser.observe().screenshot_png)
        result.finished_at = _now()
        return result

    def _observe(self, browser: BrowserDriver, target: Mapping[str, Any] | None) -> tuple[Observation, Element | None]:
        """The page, and the recorded element once it shows up (pages load asynchronously)."""
        observation = browser.observe()
        for attempt in range(self.find_attempts):
            if attempt:
                browser.wait(self.pause_s)
                observation = browser.observe()
            if not target:
                return observation, None
            rows = browser.row_texts() if target.get("row") else None
            element = find_target(target, observation.elements, rows)
            if element is not None:
                return observation, element
        return observation, None

    def _execute(
        self, browser: BrowserDriver, entry: Mapping[str, Any], element: Element | None, secrets: Secrets
    ) -> Outcome:
        kind = entry.get("action")
        if kind in TARGETED:
            target = entry["target"]
            name = target_name(target) or str(target.get("tag", "?"))
            if element is None:
                raise ValueError(t("replay.not_found", name=name))
            recorded = target.get("checked")
            if recorded is not None and element.checked is not None and element.checked != recorded:
                state = {True: t("replay.checked"), False: t("replay.unchecked")}
                raise ValueError(
                    t("replay.state_changed", name=name, recorded=state[recorded], now=state[element.checked])
                )
            expect = target_name(target) or None
            if kind == "click":
                return Outcome(browser.click(element.ref, expect=expect))
            if kind == "type":
                text = secrets.substitute(str(entry.get("text", "")))
                return Outcome(browser.type_text(element.ref, text, truthy(entry.get("submit")), expect=expect))
            return Outcome(browser.select(element.ref, secrets.substitute(str(entry.get("option", ""))), expect=expect))
        if kind == "navigate":
            return Outcome(browser.navigate(str(entry.get("url", ""))))
        if kind == "press":
            return Outcome(browser.press(str(entry.get("key", "Enter"))))
        if kind == "scroll":
            return Outcome(browser.scroll(str(entry.get("direction", "down"))))
        if kind == "wait":
            return Outcome(browser.wait(float(entry.get("seconds", 1))))
        if kind == "back":
            return Outcome(browser.go_back())
        if kind == "note":
            return Outcome(t("replay.note", note=entry.get("note", "")))
        if kind == "check":
            return self._check(browser, entry, secrets)
        raise ValueError(f"Unknown action: {kind}")

    def _check(self, browser: BrowserDriver, entry: Mapping[str, Any], secrets: Secrets) -> Outcome:
        if entry.get("replayable") is False:
            return Outcome(t("replay.skipped_check", meaning=entry.get("meaning", "")))
        absent = bool(entry.get("absent"))
        found = CheckResult.failed("not checked")
        for attempt in range(self.check_attempts):  # the page may still be updating
            if attempt:
                browser.wait(self.pause_s)
            if entry.get("url"):
                found = browser.check_url(str(entry["url"]), absent=absent)
            elif entry.get("meaning") and not absent:
                # The judge read the page text plus the state of the form controls and the recent
                # notifications: the quote is looked up in the same place.
                quote = secrets.substitute(str(entry.get("text", "")))
                if normalize(quote) and normalize(quote) in normalize(browser.page_text()):
                    found = CheckResult.passed(f'"{quote}" found in the page and the state of its controls')
                else:
                    found = CheckResult.failed(f'"{quote}" not found in the page nor in the state of its controls')
            else:
                found = browser.check_text(secrets.substitute(str(entry.get("text", ""))), absent=absent)
            if found.ok:
                break
        return Outcome(found.message, check=found.ok)
