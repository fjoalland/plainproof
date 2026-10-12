"""Launching a browser: Playwright's Chromium first, then an installed Chrome or Edge, with a clear error."""

from types import SimpleNamespace
from typing import Any

import pytest
from playwright.sync_api import Error

from plainproof.browser.playwright import BrowserLauncher, launch_browser
from plainproof.errors import ConfigError


class Chromium:
    def __init__(self, working: set[str | None]) -> None:
        self.working, self.tried = working, []

    def launch(self, channel: str | None = None, **kwargs: Any) -> str:
        self.tried.append(channel)
        if channel not in self.working:
            raise Error(f"Executable doesn't exist for {channel or 'chromium'}\nmore details")
        return f"browser:{channel}"


def playwright(working: set[str | None]) -> Any:
    return SimpleNamespace(
        chromium=Chromium(working),
        firefox=SimpleNamespace(launch=lambda **_: "firefox"),
        webkit=SimpleNamespace(launch=lambda **_: "webkit"),
    )


def test_the_bundled_chromium_first() -> None:
    fake = playwright({None, "chrome"})
    assert launch_browser(fake, "chromium") == "browser:None"
    assert fake.chromium.tried == [None]


def test_an_installed_chrome_or_edge_when_chromium_is_missing() -> None:
    fake = playwright({"msedge"})
    assert launch_browser(fake, "chromium") == "browser:msedge"
    assert fake.chromium.tried == [None, "chrome", "msedge"]


def test_an_explicit_channel_has_no_fallback() -> None:
    fake = playwright({None})
    with pytest.raises(ConfigError, match=r"Cannot start chrome: Executable doesn't exist for chrome\. Install it"):
        launch_browser(fake, "chrome")
    assert fake.chromium.tried == ["chrome"]


def test_other_engines() -> None:
    assert launch_browser(playwright(set()), "firefox") == "firefox"
    assert launch_browser(playwright(set()), "webkit") == "webkit"


def test_unknown_names_are_refused_early() -> None:
    with pytest.raises(ConfigError, match="netscape"):
        BrowserLauncher(browser_name="netscape")
