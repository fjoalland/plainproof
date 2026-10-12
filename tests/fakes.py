"""Test doubles: a browser without Playwright, for the agent and the replay."""

from __future__ import annotations

import io
from pathlib import Path
from types import TracebackType

from PIL import Image

from plainproof.browser.model import CheckResult, Element, Observation
from plainproof.text import normalize


def png(width: int = 40, height: int = 20) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class FakeBrowser:
    """Just enough of a browser for the agent loop: a page text, a URL and a list of elements.

    Every action is recorded in ``calls``. Override a method in a subclass to script a page.
    """

    def __init__(
        self, text: str = "Welcome home", url: str = "http://app/#/home", elements: list[Element] | None = None
    ) -> None:
        self.text = text
        self._url = url
        self.elements = elements or []
        self.calls: list[tuple[object, ...]] = []
        self.typed: set[str] = set()
        self.video_path: Path | None = None
        self.observe_error: Exception | None = None

    @property
    def url(self) -> str:
        return self._url

    def __enter__(self) -> FakeBrowser:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    def observe(self) -> Observation:
        if self.observe_error is not None:
            raise self.observe_error
        image = png()
        return Observation(
            url=self._url, title="App", elements=list(self.elements), screenshot_png=image, annotated_png=image
        )

    def settle(self) -> None:
        pass

    def navigate(self, url: str) -> str:
        self.calls.append(("navigate", url))
        self._url = url
        return f"Navigated to {url}"

    def click(self, ref: int | None, expect: str | None = None) -> str:
        self.calls.append(("click", ref))
        return f"Clicked [{ref}]"

    def type_text(self, ref: int | None, text: str, submit: bool = False, expect: str | None = None) -> str:
        self.calls.append(("type", ref, text))
        self.typed.add(normalize(text))
        return f'Typed "{text}" into [{ref}]'

    def select(self, ref: int | None, option: str, expect: str | None = None) -> str:
        self.calls.append(("select", ref, option))
        return f'Selected "{option}" in [{ref}]'

    def press(self, key: str) -> str:
        self.calls.append(("press", key))
        return f"Pressed {key}"

    def scroll(self, direction: str = "down") -> str:
        self.calls.append(("scroll", direction))
        return f"Scrolled {direction}"

    def wait(self, seconds: float = 1.0) -> str:
        self.calls.append(("wait", seconds))
        return f"Waited {seconds}s"

    def go_back(self) -> str:
        self.calls.append(("back",))
        return "Went back"

    def check_text(self, text: str, absent: bool = False) -> CheckResult:
        self.calls.append(("check", text, absent))
        found = normalize(text) in normalize(self.text)
        if absent:
            return (
                CheckResult.passed(f'"{text}" is absent from the page')
                if not found
                else CheckResult.failed(f'"{text}" is still present')
            )
        return CheckResult.passed(f'"{text}" found') if found else CheckResult.failed(f'"{text}" not found in page')

    def check_url(self, fragment: str, absent: bool = False) -> CheckResult:
        found = fragment in self._url
        if absent:
            return CheckResult.passed("URL does not contain it") if not found else CheckResult.failed("still in URL")
        return CheckResult.passed("URL contains it") if found else CheckResult.failed("not in URL")

    def page_text(self) -> str:
        return self.text

    def only_in_typed_fields(self, text: str) -> bool:
        return normalize(text) in self.typed and normalize(text) not in normalize(self.text)

    def row_texts(self) -> dict[str, str]:
        return {}
