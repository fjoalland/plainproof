"""The browser as the agent and the replay see it.

:class:`~plainproof.browser.playwright.PlaywrightBrowser` is the implementation shipped
with plainproof. Another automation library can be plugged in by implementing this protocol.
Action methods return a sentence for the model ("Clicked [3] "Save""); they raise
``ValueError`` with guidance when the action cannot be performed ("[9] does not exist...").
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Protocol

from .model import CheckResult, Observation


class BrowserDriver(Protocol):
    video_path: Path | None
    """Where to save the video of the session, when it is recorded (set before entering)."""

    @property
    def url(self) -> str: ...

    def __enter__(self) -> BrowserDriver: ...

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None: ...

    def observe(self) -> Observation:
        """Number the interactive elements and take the screenshots."""
        ...

    def navigate(self, url: str) -> str: ...

    def click(self, ref: int | None, expect: str | None = None) -> str: ...

    def type_text(self, ref: int | None, text: str, submit: bool = False, expect: str | None = None) -> str: ...

    def select(self, ref: int | None, option: str, expect: str | None = None) -> str: ...

    def press(self, key: str) -> str: ...

    def scroll(self, direction: str = "down") -> str: ...

    def wait(self, seconds: float = 1.0) -> str: ...

    def go_back(self) -> str: ...

    def check_text(self, text: str, absent: bool = False) -> CheckResult: ...

    def check_url(self, fragment: str, absent: bool = False) -> CheckResult: ...

    def page_text(self) -> str:
        """What a verification judged on meaning reads: text, control states, recent notifications."""
        ...

    def only_in_typed_fields(self, text: str) -> bool:
        """True when ``text`` is on the page only because the agent typed it into a field."""
        ...

    def row_texts(self) -> dict[str, str]:
        """{element number: text of its table row} for the elements of the last observation."""
        ...

    def settle(self) -> None:
        """Give the page a moment to finish what the last action started."""
        ...
