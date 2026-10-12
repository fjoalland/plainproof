"""Browser session lifecycle: launching, closing, recording the video."""

import subprocess
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Playwright

from plainproof.browser.playwright import BrowserLauncher, PlaywrightBrowser, launch_browser
from plainproof.errors import ConfigError

LAUNCH_ALONE = """
from plainproof.browser.playwright import BrowserLauncher, PlaywrightBrowser, launch_browser
with PlaywrightBrowser(headless=True) as session:
    session.page.set_content("<h1>alone</h1>")
    print(session.page.inner_text("h1"))
try:
    session.page
except RuntimeError as err:
    print(err)
"""


def test_a_session_can_launch_its_own_browser() -> None:
    # In a separate process: Playwright's sync API allows one instance per thread, and this
    # test session already runs one.
    done = subprocess.run([sys.executable, "-c", LAUNCH_ALONE], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "alone",
        "Browser session not started: use `with PlaywrightBrowser() as browser:`",
    ]


def test_an_unknown_browser_is_a_configuration_error() -> None:
    with pytest.raises(ConfigError, match="netscape"):
        PlaywrightBrowser(browser_name="netscape")


def test_the_video_is_saved_where_asked(chromium: Browser, tmp_path: Path) -> None:
    session = PlaywrightBrowser(shared_browser=chromium, record_video=True)
    session.video_path = tmp_path / "scenario" / "video.webm"
    with session:
        session.page.set_content("<h1>recorded</h1>")
        session.page.wait_for_timeout(300)
    assert session.video_path.is_file()
    assert session.video_path.stat().st_size > 0
    assert not (tmp_path / "scenario" / "_video").exists()


def test_closing_never_raises_even_if_the_page_is_already_gone(chromium: Browser) -> None:
    session = PlaywrightBrowser(shared_browser=chromium)
    with session:
        session.page.close()
    # the shared browser is still usable by other sessions
    with PlaywrightBrowser(shared_browser=chromium) as other:
        other.page.set_content("<p>ok</p>")


def test_a_launcher_gives_every_scenario_a_fresh_isolated_context(playwright_instance: Playwright) -> None:
    with BrowserLauncher(playwright=playwright_instance, settle_ms=10) as launcher:
        with launcher.session() as first:
            first.page.set_content("<p>first</p>")
            first.page.context.add_cookies([{"name": "seen", "value": "1", "url": "http://plainproof.test/"}])
        with launcher.session() as second:
            assert second.page.context.cookies("http://plainproof.test/") == [], "nothing leaks between scenarios"
    with pytest.raises(RuntimeError, match="not started"):
        launcher.session()


def test_launch_browser_starts_playwright_s_chromium(playwright_instance: Playwright) -> None:
    browser = launch_browser(playwright_instance, "chromium", headless=True)
    try:
        assert browser.is_connected()
    finally:
        browser.close()
