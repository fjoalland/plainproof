"""Browser tests: one headless Chromium for the whole session, a fresh context per test.

Pages are local HTML (no network). ``show()`` serves the HTML at a fake address so that
scripts installed on every new page (transient notifications) run as on a real site.
"""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Playwright, sync_playwright

from plainproof.browser.playwright import PlaywrightBrowser

TEST_URL = "http://plainproof.test/"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/browser/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session")
def playwright_instance() -> Iterator[Playwright]:
    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture(scope="session")
def chromium(playwright_instance: Playwright) -> Iterator[Browser]:
    browser = playwright_instance.chromium.launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture
def browser(chromium: Browser) -> Iterator[PlaywrightBrowser]:
    with PlaywrightBrowser(shared_browser=chromium, settle_ms=50) as session:
        yield session


def show(session: PlaywrightBrowser, html: str, url: str = TEST_URL) -> None:
    """Serve ``html`` at ``url`` and open it (a real navigation, unlike set_content)."""
    session.page.route(url, lambda route: route.fulfill(body=html, content_type="text/html; charset=utf-8"))
    session.page.goto(url)
