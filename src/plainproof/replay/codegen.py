"""A recording written as a plain Playwright test (pytest-playwright): readable, and runnable
without plainproof. It has none of plainproof's help with dropdowns, dates and overlays, so a
tricky widget may need a manual touch; ``plainproof replay`` remains the reference replay."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..i18n import t
from .targets import target_name

if TYPE_CHECKING:
    from ..scenario import Scenario

_IMPLICIT_ROLES = {"a": "link", "button": "button", "select": "combobox", "textarea": "textbox"}
_TEXT_INPUTS = {"", "text", "email", "password", "search", "tel", "url", "number"}
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")


def _role(target: Mapping[str, Any]) -> str:
    if target.get("role"):
        return str(target["role"])
    tag, kind = str(target.get("tag", "")), str(target.get("type", ""))
    if tag == "input":
        if kind in ("checkbox", "radio"):
            return kind
        return "textbox" if kind in _TEXT_INPUTS else ""
    return _IMPLICIT_ROLES.get(tag, "")


def accessible_name(target: Mapping[str, Any], role: str) -> str:
    """What Playwright can match against the accessible name. plainproof labels a field with the
    text of its <label> (required star included) followed by its placeholder in parentheses
    ("End date * (Pick a date)"): only the core is kept."""
    name = target_name(target)
    if target.get("tag") in ("input", "textarea", "select") or role in ("textbox", "combobox"):
        name = re.sub(r"\s*\([^()]*\)\s*$", "", name)
    core = re.sub(r"\s*\*\s*$", "", name).strip()
    return core or target_name(target)


def _text(value: str) -> str:
    """Python expression for a text: ${NAME} placeholders are read from the environment."""
    return f"_v({value!r})" if "${" in value else repr(value)


def _locator(target: Mapping[str, Any]) -> str:
    role, nth = _role(target), int(target.get("nth", 0))
    name = accessible_name(target, role)
    dates = _DATE_RE.findall(str(target.get("row", "")))
    if dates and role and name:
        # the row is found by its dates; an identifier in the name may differ from one run to the next
        rows = 'page.get_by_role("row")' + "".join(f".filter(has_text={d!r})" for d in dates)
        pattern = re.sub(r"\d+", r"\\d+", re.escape(name))
        return f"{rows}.get_by_role({role!r}, name=re.compile({pattern!r}))"
    if role and name:
        return f"page.get_by_role({role!r}, name={name!r}).nth({nth})"
    if name:
        return f"page.get_by_text({name!r}, exact=True).nth({nth})"
    return f"page.locator({target.get('tag') or '*'!r}).nth({nth})  # element without a name: to adapt"


def _check_lines(entry: Mapping[str, Any]) -> list[str]:
    negation = "not_" if entry.get("absent") else ""
    if entry.get("replayable") is False:
        return [f"    # {t('replay.py_unverifiable')}: {entry.get('meaning', '')}"]
    if entry.get("url"):
        return [f"    expect(page).{negation}to_have_url(re.compile(re.escape({entry['url']!r})))"]
    lines = [f"    # {entry['meaning']}"] if entry.get("meaning") else []
    text = _text(str(entry.get("text", "")))
    return [*lines, f'    expect(page.locator("body")).{negation}to_contain_text({text}, ignore_case=True)']


def _action_lines(entry: Mapping[str, Any]) -> list[str]:
    kind, target = entry["action"], entry.get("target")
    if kind == "check":
        return _check_lines(entry)
    if kind == "note":
        return [f"    # {t('replay.py_note')}: {entry.get('note', '')}"]
    simple = {
        "press": f"    page.keyboard.press({entry.get('key', 'Enter')!r})",
        "scroll": f"    page.mouse.wheel(0, {600 if entry.get('direction', 'down') == 'down' else -600})",
        "wait": f"    page.wait_for_timeout({int(float(entry.get('seconds', 1)) * 1000)})",
        "back": "    page.go_back()",
        "navigate": f"    page.goto({entry.get('url', '')!r})",
    }
    if kind in simple:
        return [simple[kind]]
    if not target:
        return []
    locator = _locator(target)
    lines = []
    if target.get("checked") is not None:
        lines.append(f"    expect({locator}).{'to_be_checked' if target['checked'] else 'not_to_be_checked'}()")
    if kind == "click":
        lines.append(f"    {locator}.click()")
    elif kind == "type":
        lines.append(f"    {locator}.fill({_text(str(entry.get('text', '')))})")
        if entry.get("submit"):
            lines.append(f'    {locator}.press("Enter")')
    elif kind == "select":
        option = _text(str(entry.get("option", "")))
        if target.get("tag") == "select":
            lines.append(f"    {locator}.select_option(label={option})")
        else:  # a custom dropdown: open it, then click the option
            lines.append(f"    {locator}.click()")
            lines.append(f'    page.get_by_role("option", name={option}).click()')
    return lines


def to_pytest(recording: Mapping[str, Any], scenario: Scenario) -> str:
    from .storage import test_function_name  # storage writes what this module generates

    function = test_function_name(scenario.path.stem if scenario.path else scenario.name)
    header = t("replay.py_header", name=scenario.name, date=recording.get("recorded_at", "?"))
    lines = [
        f'"""{header}',
        "",
        t("replay.py_run"),
        '"""',
        "",
        "import os",
        "import re",
        "",
        "from playwright.sync_api import Page, expect",
        "",
        f'URL = os.environ.get("PLAINPROOF_URL", {recording.get("start_url", "")!r})',
        "",
        "",
        "def _v(text: str) -> str:",
        '    return re.sub(r"\\$\\{(\\w+)\\}", lambda m: os.environ[m.group(1)], text)',
        "",
        "",
        f"def test_{function}(page: Page) -> None:",
        "    page.goto(URL)",
    ]
    for entry in recording.get("steps", []):
        lines += _action_lines(entry)
    return "\n".join(lines) + "\n"
