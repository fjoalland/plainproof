"""The browser driver, built on Playwright.

It numbers the interactive elements of the page, takes the screenshots, and performs the
actions the model chooses, deterministically: by element number confirmed by its label,
never by pixel coordinates guessed by the model.

Lessons learned on real single-page applications, each one covered by a test:

- Checkboxes and radios are often an invisible native input over a styled box: they are
  listed anyway, labelled from their <label>, aria attributes or table headers.
- Custom dropdowns open a [role=listbox]: ``select`` looks for the option only inside it,
  never in the whole page (a page-wide match once clicked a sidebar link of the same name).
- Date fields open a calendar on focus: ``type_text`` commits the value and closes it.
- When an action fails, the error says what exists instead (options, numbers, values), so
  the model can try another way rather than repeating itself.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from playwright.sync_api import Browser, BrowserContext, Error, Locator, Page, Playwright, Video, sync_playwright

from ..errors import ConfigError
from ..text import normalize
from .imaging import annotate
from .matching import TargetError, match_option, resolve_target
from .model import CheckResult, Element, Observation
from .scripts import script
from .video import reencode

REF_ATTR = "data-pp-ref"
BROWSERS = ("chromium", "chrome", "msedge", "firefox", "webkit")

_IS_CHECKED_JS = "el => el.checked === true || el.getAttribute('aria-checked') === 'true'"
_VALUE_JS = "el => (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') ? String(el.value) : null"
_IS_PASSWORD_JS = "el => el.tagName === 'INPUT' && el.type === 'password'"
_LOOKS_LIKE_DATE_JS = (
    "el => el.tagName === 'INPUT' && (el.type === 'date' || el.getAttribute('aria-haspopup') === 'dialog'"
    " || !!el.closest('.p-datepicker, .p-calendar, [data-pc-name=datepicker], [data-pc-name=calendar]'))"
)
_NAME_JS = (
    "el => (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('title') || '')"
    ".trim().slice(0, 60)"
)
_TRANSIENT_SINCE_JS = "(mark) => (window.__ppTransient || []).filter(e => e.t >= mark).map(e => e.text)"
_OPEN_OVERLAYS = (
    ".p-datepicker-panel:visible, .p-datepicker-calendar-container:visible, .p-overlay:visible, "
    "[role=dialog][aria-modal=false]:visible"
)
_LISTBOXES = (
    "[role=listbox]:visible, [role=menu]:visible, .p-select-list:visible, .p-autocomplete-list:visible, "
    ".p-dropdown-items:visible, ul.p-listbox-list:visible"
)
_OPTIONS = "[role=option], li, [data-pc-section=option], .p-select-option, .p-autocomplete-option"


def _check_browser_name(name: str) -> None:
    if name not in BROWSERS:
        raise ConfigError(f"Unknown browser {name!r}: choose one of {', '.join(BROWSERS)}.")


def launch_browser(playwright: Playwright, name: str = "chromium", headless: bool = True, slow_mo: int = 0) -> Browser:
    """Launch a browser. For "chromium", Playwright's own build first, then an installed Chrome or Edge."""
    _check_browser_name(name)
    kwargs: dict[str, Any] = {"headless": headless, "slow_mo": slow_mo}
    if name == "firefox":
        return playwright.firefox.launch(**kwargs)
    if name == "webkit":
        return playwright.webkit.launch(**kwargs)
    channels: list[str | None] = [None, "chrome", "msedge"] if name == "chromium" else [name]
    first_error: Error | None = None
    for channel in channels:
        try:
            return (
                playwright.chromium.launch(channel=channel, **kwargs)
                if channel
                else playwright.chromium.launch(**kwargs)
            )
        except Error as err:
            first_error = first_error or err
    assert first_error is not None
    raise ConfigError(
        f"Cannot start {name}: {str(first_error).splitlines()[0]}. "
        "Install it with `playwright install chromium`, or choose another one with --browser."
    )


class BrowserLauncher:
    """One browser for a whole suite; each scenario gets a fresh, isolated context (no cookie,
    storage or cache shared with the others), which is much faster than a browser per scenario::

        with BrowserLauncher(headless=True) as launcher:
            with launcher.session() as browser:
                ...
    """

    def __init__(
        self,
        *,
        browser_name: str = "chromium",
        headless: bool = True,
        slow_mo: int = 0,
        playwright: Playwright | None = None,
        **session_options: Any,
    ) -> None:
        """``playwright``: an already started Playwright to use (it is then left running)."""
        _check_browser_name(browser_name)
        self.browser_name = browser_name
        self.headless = headless
        self.slow_mo = slow_mo
        self.session_options = session_options
        self._given_playwright = playwright
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def __enter__(self) -> BrowserLauncher:
        self._playwright = self._given_playwright or sync_playwright().start()
        try:
            self._browser = launch_browser(self._playwright, self.browser_name, self.headless, self.slow_mo)
        except BaseException:
            self._stop_playwright()
            raise
        return self

    def _stop_playwright(self) -> None:
        if self._playwright is not None and self._given_playwright is None:
            self._playwright.stop()  # only when this launcher started it

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        for close in (self._browser.close if self._browser else None, self._stop_playwright):
            try:
                if close is not None:
                    close()
            except Exception:  # noqa: BLE001 - best effort teardown
                pass
        self._browser = None
        self._playwright = None

    def session(self) -> PlaywrightBrowser:
        if self._browser is None:
            raise RuntimeError("Launcher not started: use `with BrowserLauncher() as launcher:`")
        return PlaywrightBrowser(shared_browser=self._browser, browser_name=self.browser_name, **self.session_options)


class PlaywrightBrowser:
    """A browser session. Use it as a context manager::

        with PlaywrightBrowser(headless=True) as browser:
            browser.navigate("https://example.com")
            observation = browser.observe()

    ``shared_browser`` reuses an already launched Playwright browser (one context per session):
    much faster when many sessions run in a row, as in plainproof's own tests.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        viewport: tuple[int, int] = (1280, 800),
        locale: str = "en-US",
        slow_mo: int = 0,
        max_elements: int = 150,
        record_video: bool = False,
        browser_name: str = "chromium",
        settle_ms: int = 300,
        shared_browser: Browser | None = None,
    ) -> None:
        _check_browser_name(browser_name)
        self.headless = headless
        self.viewport = viewport
        self.locale = locale
        self.slow_mo = slow_mo
        self.max_elements = max_elements
        self.record_video = record_video
        self.browser_name = browser_name
        self.settle_ms = settle_ms
        self.video_path: Path | None = None
        self._shared = shared_browser
        self._playwright: Playwright | None = None
        self._own_browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last: dict[int, Element] = {}
        self._mark = 0.0
        self._typed: set[str] = set()

    # -- lifecycle ------------------------------------------------------------------------------
    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser session not started: use `with PlaywrightBrowser() as browser:`")
        return self._page

    @property
    def url(self) -> str:
        return self.page.url

    def __enter__(self) -> PlaywrightBrowser:
        browser = self._shared
        if browser is None:
            self._playwright = sync_playwright().start()
            browser = self._own_browser = launch_browser(
                self._playwright, self.browser_name, self.headless, self.slow_mo
            )
        size = {"width": self.viewport[0], "height": self.viewport[1]}
        options: dict[str, Any] = {"viewport": size, "locale": self.locale}
        if self.record_video and self.video_path is not None:
            options.update(record_video_dir=str(self._video_tmp()), record_video_size=size)
        self._context = browser.new_context(**options)
        self._context.add_init_script(script("transient"))
        self._page = self._context.new_page()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        # Closing must never raise: a page still navigating or a run interrupted with Ctrl-C
        # would otherwise hide the real outcome behind a teardown error.
        video = self._page.video if self._page is not None and self.record_video and self.video_path else None
        steps = (
            self._page.close if self._page is not None else None,
            self._context.close if self._context is not None else None,
            lambda: self._save_video(video),  # complete once its context is closed
            self._own_browser.close if self._own_browser is not None else None,
            self._playwright.stop if self._playwright is not None else None,
        )
        for step in steps:
            try:
                if step is not None:
                    step()
            except Exception:  # noqa: BLE001 - best effort teardown
                pass
        self._page = None
        self._context = None
        self._own_browser = None
        self._playwright = None

    def _video_tmp(self) -> Path:
        assert self.video_path is not None
        return self.video_path.parent / "_video"

    def _save_video(self, video: Video | None) -> None:
        if video is None or self.video_path is None:
            return
        try:
            video.save_as(str(self.video_path))
            video.delete()
        finally:
            shutil.rmtree(self._video_tmp(), ignore_errors=True)
        reencode(self.video_path)

    # -- observation ----------------------------------------------------------------------------
    def observe(self) -> Observation:
        page = self.page
        raw: dict[str, Any] = {}
        for attempt in range(3):  # a navigation may still be in flight: wait and retry
            self.settle()
            try:
                raw = page.evaluate(script("extract"), {"refAttr": REF_ATTR, "max": self.max_elements})
                break
            except Error:
                if attempt == 2:
                    raise
                page.wait_for_timeout(1000)
        elements = [Element.from_js(e) for e in raw.get("elements", [])]
        self._last = {e.ref: e for e in elements}
        png = page.screenshot(type="png")
        return Observation(
            url=page.url,
            title=page.title(),
            elements=elements,
            screenshot_png=png,
            annotated_png=annotate(png, elements),
            truncated=int(raw.get("truncated", 0)),
        )

    def settle(self) -> None:
        page = self.page
        with contextlib.suppress(Error):  # some pages are never idle
            page.wait_for_load_state("networkidle", timeout=3000)
        page.wait_for_timeout(self.settle_ms)

    # -- actions ----------------------------------------------------------------------------------
    def navigate(self, url: str) -> str:
        self._mark_action()
        if not url.startswith(("http://", "https://", "file:", "about:")):
            url = "https://" + url
        self.page.goto(url, wait_until="domcontentloaded")
        return f"Navigated to {url}"

    def click(self, ref: int | None, expect: str | None = None) -> str:
        self._mark_action()
        target, note = self._resolve(ref, expect)
        locator = self._find(target)
        element = self._last.get(target)
        if locator is None:  # re-rendered by the framework: click where it was
            self._click_position(target)
            return self._sentence(
                f"Clicked [{target}]", self._quoted_name(target), "(by position, element was re-rendered)"
            )
        description = self._name_of(locator)
        if element is not None and (element.kind in ("checkbox", "radio") or not description):
            description = self._quoted_name(target) or description
        how = ""
        try:
            locator.click(timeout=5000)
        except Error:
            # Covered by an overlay, animating or detached: click where it was, then force.
            try:
                self._click_position(target)
                how = " (by position)"
            except (Error, ValueError):
                locator.click(timeout=3000, force=True)
                how = " (forced)"
        result = self._sentence(f"Clicked [{target}]", description) + how + note
        if element is not None and element.expanded:
            try:
                now = locator.get_attribute("aria-expanded")
                if now in ("true", "false"):
                    result += " (submenu now " + ("open" if now == "true" else "closed") + ")"
            except Error:
                pass
        if element is not None and element.kind in ("checkbox", "radio"):
            with contextlib.suppress(Error):
                result += " (now checked)" if locator.evaluate(_IS_CHECKED_JS) else " (now unchecked)"
        return result

    def type_text(self, ref: int | None, text: str, submit: bool = False, expect: str | None = None) -> str:
        self._mark_action()
        target, note = self._resolve(ref, expect)
        locator = self._find(target)
        element = self._last.get(target)
        if element is not None and (
            element.tag == "button" or (element.role == "button" and element.tag not in ("input", "textarea"))
        ):
            # A button cannot be typed into: use the field it decorates (calendar or search icon).
            sibling = self._sibling_input(locator)
            if sibling is None:
                raise ValueError(
                    f"[{target}] is a button, not a text field. Type into the <input> next to it "
                    "(find it in the element list)."
                )
            locator, element = sibling, None
            note += " (redirected from the button to the text field next to it)"
        if locator is None:
            self._click_position(target)
        else:
            locator.click(timeout=5000)
        page = self.page
        # Through the keyboard: some sites swap the input on focus, and a locator bound to the
        # old element would time out.
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(text, delay=20)
        password = self._evaluate_bool(locator, _IS_PASSWORD_JS)
        if not password and normalize(text):
            self._typed.add(normalize(text))
        is_date = (element is not None and element.kind == "date") or (
            element is None and self._evaluate_bool(locator, _LOOKS_LIKE_DATE_JS)
        )
        if submit:
            page.keyboard.press("Enter")
        elif is_date:
            # Commit the value and close the calendar, so element numbers stay stable.
            page.keyboard.press("Tab")
            page.wait_for_timeout(200)
            self._close_overlays()
        else:
            page.wait_for_timeout(self.settle_ms * 2)  # let autocomplete lists show up
        then = " then pressed Enter" if submit else ""
        if password:
            # Never echo a password, nor "***": the model would read it as a failed entry and retype it.
            return f"Typed the secret value into [{target}]{note} (password entered){then}"
        result = f'Typed "{text}" into [{target}]{note}{then}'
        value = self._value_of(locator)
        if value is not None:
            if normalize(value) == normalize(text):
                result += f' (value now "{value}")'
            elif value == "":
                result += " (WARNING: the field is empty afterwards, the value was not accepted)"
            else:
                result += f' (WARNING: the field now shows "{value}")'
        if is_date and not submit:
            result += " (calendar closed)"
        return result

    def select(self, ref: int | None, option: str, expect: str | None = None) -> str:
        self._mark_action()
        target, _ = self._resolve(ref, expect)
        locator = self._find(target)
        element = self._last.get(target)
        page = self.page
        if locator is not None and element is not None and element.tag == "select":
            return self._select_native(locator, element, option)
        # Custom dropdown: open it (typing into it when it is an autocomplete field), then pick
        # the option INSIDE the list that appeared.
        if locator is None:
            self._click_position(target)
        else:
            try:
                locator.click(timeout=5000)
            except Error:
                try:
                    self._click_position(target)
                except (Error, ValueError):
                    locator.click(timeout=3000, force=True)
        if element is not None and element.tag == "input" and element.kind != "date":
            page.keyboard.press("ControlOrMeta+A")
            page.keyboard.press("Backspace")
            page.keyboard.type(option, delay=20)
        listbox = self._wait_listbox()
        if listbox is None:
            raise ValueError(
                f"No option list opened after clicking [{target}]. It may not be a dropdown: "
                "click it and read the numbered elements that appear."
            )
        search = self._overlay_filter(listbox, target)
        if search is not None:  # a filter box inside the overlay shortens long lists
            try:
                search.fill(option, timeout=2000)
                page.wait_for_timeout(400)
            except Error:
                pass
        options = listbox.locator(_OPTIONS)
        texts = self._texts(options)
        index = match_option(texts, option)
        if index is None:
            available = [t for t in texts if t][:20]
            if search is not None:
                # Leave the list as found: a filter left with a text matching nothing makes every
                # later opening of this dropdown look empty.
                try:
                    search.fill("", timeout=2000)
                    page.wait_for_timeout(200)
                    available = [t for t in self._texts(options) if t][:20] or available
                except Error:
                    pass
            page.keyboard.press("Escape")
            raise ValueError(
                f'Option "{option}" is not in the open list of [{target}]. Available options: {available}. '
                "Pick one of them (exact label) or scroll the list."
            )
        chosen = options.nth(index)
        with contextlib.suppress(Error):
            chosen.scroll_into_view_if_needed(timeout=2000)
        chosen.click(timeout=5000)
        page.wait_for_timeout(200)
        result = f'Selected "{texts[index]}" in [{target}] (custom dropdown)'
        value = self._value_of(locator)
        return result + (f' (field now shows "{value}")' if value else "")

    @staticmethod
    def _select_native(locator: Locator, element: Element, option: str) -> str:
        """A native <select>: the option observed on the page that matches (case and accents
        ignored), else the given text as a label, then as a value (long lists are only partly observed)."""
        index = match_option(element.options, option)
        attempts = [("label", element.options[index])] if index is not None else []
        attempts += [("label", option), ("value", option)]
        for by, text in attempts:
            try:
                if by == "label":
                    locator.select_option(label=text, timeout=1000)
                else:
                    locator.select_option(value=text, timeout=1000)
            except Error:
                continue
            return f'Selected "{text}" in [{element.ref}]'
        raise ValueError(f'Option "{option}" is not in <select> [{element.ref}]. Available: {list(element.options)}')

    def press(self, key: str) -> str:
        self._mark_action()
        self.page.keyboard.press(key)
        return f"Pressed {key}"

    def scroll(self, direction: str = "down", amount: int = 600) -> str:
        page = self.page
        before = page.evaluate("() => window.scrollY")
        page.mouse.wheel(0, amount if direction == "down" else -amount)
        page.wait_for_timeout(200)
        if page.evaluate("() => window.scrollY") == before:
            edge = "bottom" if direction == "down" else "top"
            return (
                f"Scrolled {direction}: the page did not move (already at the {edge}, "
                "or the content scrolls inside an element)"
            )
        return f"Scrolled {direction}"

    def wait(self, seconds: float = 1.0) -> str:
        self.page.wait_for_timeout(int(seconds * 1000))
        return f"Waited {seconds}s"

    def go_back(self) -> str:
        self._mark_action()
        self.page.go_back(wait_until="domcontentloaded")
        return "Went back"

    # -- checks ---------------------------------------------------------------------------------
    def check_url(self, fragment: str, absent: bool = False) -> CheckResult:
        """The current URL contains (or, with ``absent``, does not contain) a fragment."""
        url = self.page.url
        found = normalize(fragment) in normalize(url)
        if absent:
            if found:
                return CheckResult.failed(f'URL {url} still contains "{fragment}"')
            return CheckResult.passed(f'URL does not contain "{fragment}" ({url})')
        if found:
            return CheckResult.passed(f'URL contains "{fragment}" ({url})')
        return CheckResult.failed(f'URL {url} does not contain "{fragment}"')

    def check_text(self, text: str, absent: bool = False) -> CheckResult:
        """A text is present (or, with ``absent``, absent) in the visible text or the accessibility
        labels of the page, iframes included, ignoring case and accents."""
        page_text = normalize(" ".join(self._text_parts()))
        needle = normalize(text)
        index = page_text.find(needle) if needle else -1
        excerpt = page_text[max(index - 60, 0) : index + len(needle) + 60] if index >= 0 else ""
        if absent:
            if index < 0:
                return CheckResult.passed(f'"{text}" is absent from the page')
            return CheckResult.failed(f'"{text}" is still present: "...{excerpt}..."')
        if index >= 0 and self.only_in_typed_fields(text):
            return CheckResult.failed(
                f'"{text}" is only in a field you typed it into yourself, which proves nothing. '
                "It must be shown by the application (table, message, title)."
            )
        if index < 0:
            flash = self._transient_match(needle)
            if flash is not None:
                return CheckResult.passed(
                    f'"{text}" was displayed in a temporary notification, closed since: "{flash[:160]}"'
                )
            return CheckResult.failed(f'"{text}" not found in page' + self._hidden_hint(text))
        return CheckResult.passed(f'"{text}" found in "...{excerpt}..."')

    def only_in_typed_fields(self, text: str) -> bool:
        needle = normalize(text)
        if not needle or not any(needle in typed for typed in self._typed):
            return False
        return needle not in normalize(" ".join(self._text_parts(with_values=False)))

    def page_text(self) -> str:
        text = "\n".join(self._text_parts())
        try:
            controls = cast("list[str]", self.page.evaluate(script("control_states")))
        except Error:
            controls = []
        if controls:
            text += "\n\n[Form controls and their current state]\n" + "\n".join(controls)
        flashes = self._transient_since_mark()
        if flashes:
            text += "\n\n[Temporary notifications shown since the last action]\n" + "\n".join(flashes)
        return text

    def row_texts(self) -> dict[str, str]:
        try:
            return cast("dict[str, str]", self.page.evaluate(script("rows"), {"attr": REF_ATTR}) or {})
        except Error:
            return {}

    # -- internals ------------------------------------------------------------------------------
    @staticmethod
    def _sentence(*parts: str) -> str:
        return " ".join(p for p in parts if p)

    def _resolve(self, ref: int | None, expect: str | None) -> tuple[int, str]:
        try:
            return resolve_target(self._last, ref, expect)
        except TargetError as err:
            if err.kind != "missing":
                raise
            covered = self._covered_by(err.wanted)
            if covered == "fixed bar":
                raise TargetError(
                    f'"{expect}" is on the page but under a bar fixed to the top or bottom of the screen, so it '
                    'cannot be clicked where it is. Scroll ({"action": "scroll", "direction": "down"}, or "up"), '
                    "then click it with its number in the new element list. Escape changes nothing here.",
                    kind="missing",
                    wanted=err.wanted,
                ) from None
            if covered:
                raise TargetError(
                    f'"{expect}" is on the page but hidden under an open popup ({covered}), so it cannot be '
                    'clicked. Close the popup first with {"action": "press", "key": "Escape"}, then use the '
                    "new element list.",
                    kind="missing",
                    wanted=err.wanted,
                ) from None
            raise

    def _covered_by(self, wanted: str) -> str:
        try:
            return str(self.page.evaluate(script("covered"), wanted) or "")
        except Error:
            return ""

    def _find(self, ref: int) -> Locator | None:
        """The element numbered ``ref``, scrolled into view; None if it was re-rendered since."""
        locator = self.page.locator(f"[{REF_ATTR}='{ref}']")
        if locator.count() > 0:
            target = locator.first
            element = self._last.get(ref)
            if element is None or not element.on_screen:
                try:
                    target.scroll_into_view_if_needed(timeout=3000)
                    self.page.wait_for_timeout(200)
                except Error:
                    pass
            return target
        if ref in self._last:
            return None
        valid = f"1-{max(self._last)}" if self._last else "none"
        raise ValueError(
            f"Element [{ref}] does not exist in the current page (valid numbers: {valid}). "
            "Use only numbers from the element list."
        )

    def _click_position(self, ref: int) -> None:
        element = self._last[ref]
        if not element.on_screen:
            raise ValueError(
                f"Element [{ref}] was re-rendered and is no longer on the page. "
                "Use a number from the current element list."
            )
        x0, y0, x1, y1 = element.box
        self.page.mouse.click((x0 + x1) / 2, (y0 + y1) / 2)

    def _quoted_name(self, ref: int) -> str:
        element = self._last.get(ref)
        return f'"{element.name}"' if element is not None and element.name else ""

    @staticmethod
    def _name_of(locator: Locator) -> str:
        try:
            name = str(locator.evaluate(_NAME_JS))
        except Error:
            return ""
        return f'"{name}"' if name else ""

    @staticmethod
    def _value_of(locator: Locator | None) -> str | None:
        if locator is None:
            return None
        try:
            value = locator.evaluate(_VALUE_JS)
        except Error:
            return None
        return None if value is None else str(value)

    @staticmethod
    def _evaluate_bool(locator: Locator | None, js: str) -> bool:
        if locator is None:
            return False
        try:
            return bool(locator.evaluate(js))
        except Error:
            return False

    @staticmethod
    def _sibling_input(locator: Locator | None) -> Locator | None:
        """The text field a decorative button belongs to (previous sibling or same wrapper)."""
        if locator is None:
            return None
        for xpath in ("preceding-sibling::input[1]", "../input[1]", "../../input[1]", "preceding-sibling::*//input[1]"):
            try:
                candidate = locator.locator(f"xpath={xpath}")
                if candidate.count() > 0 and candidate.first.is_visible():
                    return candidate.first
            except Error:
                continue
        return None

    def _close_overlays(self) -> None:
        try:
            if self.page.locator(_OPEN_OVERLAYS).count() > 0:
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(150)
        except Error:
            pass

    def _wait_listbox(self, timeout_ms: int = 3000) -> Locator | None:
        page = self.page
        waited = 0
        while waited <= timeout_ms:
            try:
                lists = page.locator(_LISTBOXES)
                if lists.count() > 0:
                    return lists.last  # the most recently opened overlay is appended last
                options = page.locator("[role=option]:visible")
                if options.count() > 0:  # options without a listbox: their container
                    return options.first.locator("xpath=..")
            except Error:
                pass
            page.wait_for_timeout(150)
            waited += 150
        return None

    @staticmethod
    def _overlay_filter(listbox: Locator, ref: int) -> Locator | None:
        """A visible filter field in the same overlay as the list."""
        ancestor = listbox
        for _ in range(4):
            try:
                ancestor = ancestor.locator("xpath=..")
                fields = ancestor.locator(f"input:visible:not([{REF_ATTR}='{ref}'])")
                if fields.count() > 0:
                    return fields.first
            except Error:
                break
        return None

    @staticmethod
    def _texts(options: Locator) -> list[str]:
        try:
            return [" ".join(t.split()) for t in options.all_inner_texts()]
        except Error:
            return []

    def _text_parts(self, with_values: bool = True) -> list[str]:
        """Visible text and accessibility labels of the page and of its visible iframes."""
        parts = []
        page = self.page
        for frame in page.frames:
            try:
                if frame != page.main_frame and not frame.frame_element().is_visible():
                    continue  # hidden iframes (silent SSO, trackers) are not what the user sees
                parts.append(str(frame.evaluate(script("page_text"), with_values)))
            except Error:
                continue
        return parts

    def _mark_action(self) -> None:
        """Start a new window for transient notifications: a check only accepts those shown
        after the last action, never a stale one."""
        with contextlib.suppress(Error):
            self._mark = float(self.page.evaluate("() => Date.now()"))

    def _transient_since_mark(self) -> list[str]:
        try:
            return cast("list[str]", self.page.evaluate(_TRANSIENT_SINCE_JS, self._mark))
        except Error:
            return []

    def _transient_match(self, needle: str) -> str | None:
        if not needle:
            return None
        return next((t for t in reversed(self._transient_since_mark()) if needle in normalize(t)), None)

    def _hidden_hint(self, text: str) -> str:
        """When a text is in the page but folded (collapsed menu, closed accordion, inactive tab),
        say so and name the toggle that most likely reveals it."""
        try:
            found = self.page.evaluate(script("hidden_text"), {"needle": normalize(text), "refAttr": REF_ATTR})
        except Error:
            return ""
        if not found:
            return ""
        hint = " (but it IS in the page, hidden inside a collapsed section"
        if found.get("toggle"):
            ref = found.get("ref")
            hint += f': open it first by clicking "{found["toggle"]}"' + (f" [{ref}]" if ref else "")
        return hint + ", then run the check again)"
