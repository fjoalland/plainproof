"""Observing a page: which elements are numbered, with which label and state."""

from plainproof.browser.imaging import annotate
from plainproof.browser.model import Element
from plainproof.browser.playwright import PlaywrightBrowser


def by_name(elements: list[Element]) -> dict[str, Element]:
    return {e.name: e for e in elements}


def test_interactive_elements_are_numbered_and_drawn(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<h1>Demo</h1><input placeholder='Search'><button>Go</button><a href='#x'>Link</a>")
    obs = browser.observe()
    assert [(e.ref, e.tag) for e in obs.elements] == [(1, "input"), (2, "button"), (3, "a")]
    assert obs.elements[1].describe() == '[2] <button> text="Go"'
    assert obs.annotated_png
    assert obs.screenshot_png
    assert obs.annotated_png != obs.screenshot_png
    assert obs.url == "about:blank"


def test_an_overlay_hides_what_is_under_it(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        "<button>Below</button><div style='position:fixed;inset:0;background:#fff'><button>Accept</button></div>"
    )
    assert [e.text for e in browser.observe().elements] == ["Accept"]


LONG_FORM = """
<h1>New invoice</h1>
<input id="start" aria-label="Start date">
<div style="height:1500px">filler</div>
<button id="add">Add Jane DOE to the recipients</button>
<div style="height:1500px">filler</div>
<button id="create">Create the invoice</button>
"""


def test_the_whole_page_is_listed_not_only_the_viewport(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(LONG_FORM)
    elements = by_name(browser.observe().elements)
    assert elements["Start date"].off == ""
    assert elements["Start date"].on_screen
    assert elements["Create the invoice"].off == "below"
    assert not elements["Create the invoice"].on_screen


def test_an_open_modal_hides_the_page_behind_it(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        LONG_FORM + '<div role="dialog" style="position:fixed;inset:20% 30%;background:#fff;z-index:9">'
        "<p>Delete this invoice?</p><button>Yes</button></div>"
    )
    names = by_name(browser.observe().elements)
    assert "Yes" in names
    assert "Create the invoice" not in names


def test_an_open_dropdown_keeps_the_form_listed(browser: PlaywrightBrowser) -> None:
    # A list is not a modal: cutting the element list to the viewport made the agent lose the fields below.
    browser.page.set_content(
        LONG_FORM + '<ul role="listbox" style="position:fixed;top:40px;left:10px;background:#fff;z-index:9">'
        '<li role="option">Monthly</li></ul>'
    )
    names = by_name(browser.observe().elements)
    assert "Monthly" in names
    assert "Create the invoice" in names


def test_hidden_containers_are_not_listed(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        '<div style="height:2000px"></div>'
        '<div aria-hidden="true"><button>Closed menu</button></div>'
        '<div style="display:none"><button>Never shown</button></div>'
        "<button>Visible</button><button disabled>Disabled</button>"
    )
    assert list(by_name(browser.observe().elements)) == ["Visible"]


def test_a_very_long_page_is_capped_and_says_so(chromium: object) -> None:
    with PlaywrightBrowser(shared_browser=chromium, max_elements=20) as session:  # type: ignore[arg-type]
        session.page.set_content("".join(f"<button>B{i}</button><br>" for i in range(60)))
        obs = session.observe()
        assert len(obs.elements) == 20
        assert obs.truncated == 40
        assert "40 more elements" in obs.elements_text()


def test_annotation_ignores_off_screen_elements(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(LONG_FORM)
    obs = browser.observe()
    assert any(not e.on_screen for e in obs.elements)
    assert annotate(obs.screenshot_png, obs.elements)


# -- labels -------------------------------------------------------------------------------
HIDDEN_CHECKBOXES = """
<style>
  .hidden-input { position:absolute; opacity:0; width:100%; height:100%; top:0; left:0; margin:0; }
  .box { position:relative; width:20px; height:20px; border:1px solid #333; display:inline-block; }
</style>
<table><thead><tr><th></th><th>Monday</th><th>Tuesday</th></tr></thead>
<tbody><tr><th>Morning</th>
  <td><span class="box"><input type="checkbox" class="hidden-input"></span></td>
  <td><span class="box"><input type="checkbox" class="hidden-input" checked></span></td>
</tr></tbody></table>
"""


def test_invisible_checkboxes_are_listed_with_their_table_headers(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(HIDDEN_CHECKBOXES)
    boxes = [e for e in browser.observe().elements if e.kind == "checkbox"]
    assert [(e.label, e.checked) for e in boxes] == [("Monday / Morning", False), ("Tuesday / Morning", True)]


def test_a_styled_radio_gets_its_sibling_label(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        "<div class='p-radiobutton'><input type='radio' name='e' id='r1' style='opacity:0;width:20px;height:20px'>"
        "</div><label for='r1'>Yes</label>"
    )
    radio = next(e for e in browser.observe().elements if e.kind == "radio")
    assert radio.label == "Yes"


LABELLED_WRAPPERS = """
<div class="field">
  <label for="startDate">Start date <span>*</span></label>
  <span id="startDate" class="p-calendar"><input placeholder="Pick a date"><button aria-label="Choose Date">📅</button></span>
</div>
<div class="field"><label>End date <span>*</span></label><span class="p-calendar"><input></span></div>
<div class="field"><label>Two fields</label><input id="a"><input id="b"></div>
"""


def test_labels_given_to_a_wrapper_or_to_the_field_block_name_the_input(browser: PlaywrightBrowser) -> None:
    # Component libraries put the id on a wrapper: <label for="startDate"> then labels nothing.
    browser.page.set_content(LABELLED_WRAPPERS)
    inputs = [e for e in browser.observe().elements if e.tag == "input"]
    assert inputs[0].label == "Start date * (Pick a date)"
    assert inputs[1].label == "End date *"
    assert inputs[2].label == ""
    assert inputs[3].label == ""


def test_a_menu_toggle_without_href_is_listed(browser: PlaywrightBrowser) -> None:
    browser.page.set_content('<a class="dropdown-toggle">Administration</a><a href="#x">Projects</a>')
    assert "Administration" in by_name(browser.observe().elements)


def test_state_of_fields_and_menus(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        "<input aria-label='City' value='Paris'>"
        "<button aria-expanded='false'>Settings</button>"
        "<select aria-label='Size'><option>S</option><option selected>M</option></select>"
        "<input type='password' aria-label='Password' value='hunter2'>"
    )
    elements = by_name(browser.observe().elements)
    assert elements["City"].value == "Paris"
    assert elements["Settings"].expanded == "false"
    assert elements["Size"].options == ("S", "M")
    assert elements["Size"].text == "M"
    assert elements["Password"].value == ""  # a password value is never read
