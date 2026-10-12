"""Acting on a page: by element number, confirmed by label, with helpful errors."""

import pytest

from plainproof.browser.matching import TargetError
from plainproof.browser.model import Element
from plainproof.browser.playwright import PlaywrightBrowser

from .conftest import TEST_URL, show


def ref_of(browser: PlaywrightBrowser, name: str) -> int:
    return next(e.ref for e in browser.observe().elements if e.name == name)


def by_name(browser: PlaywrightBrowser) -> dict[str, Element]:
    return {e.name: e for e in browser.observe().elements}


# -- typing and clicking ------------------------------------------------------------------
def test_typing_replaces_the_value_and_reports_it(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<input aria-label='City' value='old'>")
    result = browser.type_text(ref_of(browser, "City"), "Paris")
    assert result == 'Typed "Paris" into [1] (value now "Paris")'
    assert browser.page.input_value("input") == "Paris"


def test_typing_then_enter(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<form onsubmit=\"document.title='sent';return false\"><input aria-label='Q'></form>")
    assert "then pressed Enter" in browser.type_text(ref_of(browser, "Q"), "shoes", submit=True)
    assert browser.page.title() == "sent"


def test_a_field_that_rejects_the_value_is_reported(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<input aria-label='Code' oninput=\"this.value=''\">")
    assert "WARNING: the field is empty afterwards" in browser.type_text(ref_of(browser, "Code"), "ABC")


def test_a_password_is_never_echoed(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<input type='password' aria-label='Password'>")
    result = browser.type_text(ref_of(browser, "Password"), "hunter2")
    assert "hunter2" not in result
    assert "password entered" in result
    assert browser.page.input_value("input") == "hunter2"


def test_click_names_what_it_clicked(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<button aria-label='Submit the form' onclick=\"document.title='ok'\">OK</button>")
    assert browser.click(ref_of(browser, "Submit the form")) == 'Clicked [1] "Submit the form"'
    assert browser.page.title() == "ok"


def test_click_on_a_rerendered_element_falls_back_to_its_position(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<div id='root'><button onclick=\"document.title='clicked'\">Go</button></div>")
    browser.observe()
    # a framework re-render replaces the node (and its number attribute)
    browser.page.evaluate(
        "document.getElementById('root').innerHTML = `<button onclick=\"document.title='clicked'\">Go</button>`"
    )
    assert "by position" in browser.click(1)
    assert browser.page.title() == "clicked"


def test_off_screen_elements_are_reached_without_scrolling(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        '<div style="height:3000px"></div><input aria-label="Notes">'
        "<button onclick=\"this.textContent='clicked'\">Create</button>"
    )
    elements = by_name(browser)
    browser.type_text(elements["Notes"].ref, "automatic test")
    assert "Clicked" in browser.click(elements["Create"].ref)
    assert browser.page.input_value("input") == "automatic test"
    assert browser.page.inner_text("button") == "clicked"


def test_checkbox_and_menu_clicks_report_the_new_state(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        "<label><input type='checkbox'> Remember me</label>"
        "<button aria-expanded='false' onclick=\"this.setAttribute('aria-expanded', "
        "this.getAttribute('aria-expanded') === 'true' ? 'false' : 'true')\">Menu</button>"
    )
    elements = by_name(browser)
    assert browser.click(elements["Remember me"].ref).endswith("(now checked)")
    assert browser.click(elements["Menu"].ref).endswith("(submenu now open)")


# -- the label guard ----------------------------------------------------------------------
def test_a_stale_number_is_corrected_by_the_label(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<button>Create the invoice</button><button>Add Jane DOE</button>")
    elements = by_name(browser)
    result = browser.click(elements["Add Jane DOE"].ref, expect="Create the invoice")
    assert f"[{elements['Create the invoice'].ref}]" in result
    assert "used that one" in result


def test_typing_follows_the_label_too(browser: PlaywrightBrowser) -> None:
    browser.page.set_content('<input aria-label="Start date"><input aria-label="End date">')
    elements = by_name(browser)
    browser.type_text(elements["Start date"].ref, "31/12/2050", expect="End date")
    assert browser.page.input_value('[aria-label="End date"]') == "31/12/2050"
    assert browser.page.input_value('[aria-label="Start date"]') == ""


def test_a_label_absent_from_the_page_is_refused(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<button>OK</button>")
    with pytest.raises(TargetError, match="no element on this page carries that label"):
        browser.click(ref_of(browser, "OK"), expect="Export to PDF")


def test_a_button_under_a_fixed_footer_says_to_scroll(chromium: object) -> None:
    # The agent was told to close a popup with Escape and pressed it ten times.
    with PlaywrightBrowser(shared_browser=chromium, viewport=(800, 400)) as session:  # type: ignore[arg-type]
        session.page.set_content(
            '<div style="height:360px"></div><button>Validate</button><div style="height:600px"></div>'
            '<footer style="position:fixed;bottom:0;left:0;right:0;height:60px;background:#eee">footer</footer>'
        )
        session.observe()
        with pytest.raises(ValueError, match="fixed to the top or bottom"):
            session.click(999, expect="Validate")


def test_a_button_under_an_open_calendar_says_to_close_it(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        '<div style="position:relative"><button style="position:absolute;top:100px;left:20px">Cancel</button>'
        '<div class="p-datepicker-panel" style="position:absolute;top:60px;left:0;width:300px;height:200px;'
        'background:#fff">January 2051</div></div>'
    )
    assert "Cancel" not in by_name(browser)
    with pytest.raises(ValueError, match=r"hidden under an open popup \(a calendar\).*Escape"):
        browser.click(None, expect="Cancel")


def test_an_unknown_number_lists_the_valid_ones(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<button>OK</button>")
    browser.observe()
    with pytest.raises(ValueError, match=r"\[999\] does not exist.*1-1"):
        browser.click(999)


# -- dropdowns, dates ----------------------------------------------------------------------
WIDGETS = """
<style>#overlay, #cal { display:none; position:absolute; background:#fff; border:1px solid #333; }
#overlay.open, #cal.open { display:block; }</style>
<nav><a href="#" id="side">Monthly</a></nav>
<div id="sel" role="combobox" aria-expanded="false" tabindex="0" onclick="toggle()">Choose a plan</div>
<div id="overlay"><ul role="listbox">
  <li role="option" onclick="pick(this)">Yearly</li>
  <li role="option" onclick="pick(this)">Monthly</li>
</ul></div>
<span class="dp">
  <input id="date" role="combobox" aria-haspopup="dialog" placeholder="Start date" onfocus="cal(true)" onblur="cal(false)">
  <button type="button" aria-label="Choose Date" onclick="cal(true)">📅</button>
</span>
<div id="cal" class="p-datepicker-panel">calendar</div>
<p id="out"></p>
<script>
  function toggle() { const o = document.getElementById('overlay'); o.classList.toggle('open');
    document.getElementById('sel').setAttribute('aria-expanded', o.classList.contains('open')); }
  function pick(li) { document.getElementById('sel').textContent = li.textContent; toggle();
    document.getElementById('out').textContent = 'picked ' + li.textContent; }
  function cal(open) { document.getElementById('cal').classList.toggle('open', open); }
  document.getElementById('side').onclick = e => { e.preventDefault(); document.getElementById('out').textContent = 'NAVIGATED AWAY'; };
</script>
"""


def combobox(browser: PlaywrightBrowser) -> int:
    return next(e.ref for e in browser.observe().elements if e.role == "combobox" and e.tag == "div")


def test_native_select(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<select aria-label='Size'><option>S</option><option>Medium</option></select>")
    assert browser.select(ref_of(browser, "Size"), "medium") == 'Selected "Medium" in [1]'  # case ignored
    assert browser.page.input_value("select") == "Medium"


def test_native_select_by_value(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        "<select aria-label='Size'><option value='s'>Small</option><option value='m'>Medium</option></select>"
    )
    assert browser.select(ref_of(browser, "Size"), "m") == 'Selected "Medium" in [1]'  # "m" is a prefix of Medium
    assert browser.page.input_value("select") == "m"


def test_native_select_with_an_unknown_option_lists_the_real_ones(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<select aria-label='Size'><option>S</option><option>M</option></select>")
    with pytest.raises(ValueError, match=r"Available: \['S', 'M'\]"):
        browser.select(ref_of(browser, "Size"), "XL")


def test_custom_dropdown_picks_inside_the_list_not_a_link_with_the_same_name(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(WIDGETS)
    result = browser.select(combobox(browser), "monthly")
    assert "custom dropdown" in result
    assert browser.page.inner_text("#out") == "picked Monthly"  # not "NAVIGATED AWAY"


def test_custom_dropdown_with_an_unknown_option_lists_the_real_ones(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(WIDGETS)
    with pytest.raises(ValueError, match=r"Available options: \['Yearly', 'Monthly'\]"):
        browser.select(combobox(browser), "Weekly")


def test_a_date_field_is_flagged_and_its_calendar_closed_after_typing(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(WIDGETS)
    date = next(e for e in browser.observe().elements if e.kind == "date")
    result = browser.type_text(date.ref, "01/03/2050")
    assert 'value now "01/03/2050"' in result
    assert "calendar closed" in result
    assert not browser.page.locator("#cal").is_visible()


def test_typing_into_a_calendar_button_goes_to_its_field(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(WIDGETS)
    result = browser.type_text(ref_of(browser, "Choose Date"), "31/03/2050")
    assert "redirected" in result
    assert browser.page.input_value("#date") == "31/03/2050"


def test_a_click_on_something_that_is_not_a_list_says_so(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<button>Plain</button>")
    with pytest.raises(ValueError, match="No option list opened"):
        browser.select(ref_of(browser, "Plain"), "x")


# -- navigation and keys ------------------------------------------------------------------
def test_navigate_back_press_wait_and_scroll(browser: PlaywrightBrowser) -> None:
    show(browser, "<h1>Home</h1><div style='height:3000px'></div>")
    show(browser, "<h1>Second</h1>", url=TEST_URL + "second")
    assert browser.go_back() == "Went back"
    assert browser.url == TEST_URL
    assert browser.scroll("down") == "Scrolled down"
    assert browser.scroll("up") == "Scrolled up"
    assert "did not move (already at the top" in browser.scroll("up")
    assert browser.press("Tab") == "Pressed Tab"
    assert browser.wait(0.05) == "Waited 0.05s"


def test_navigate_adds_the_scheme(browser: PlaywrightBrowser) -> None:
    browser.page.route("https://plainproof.test/", lambda r: r.fulfill(body="<h1>x</h1>", content_type="text/html"))
    assert browser.navigate("plainproof.test/") == "Navigated to https://plainproof.test/"
