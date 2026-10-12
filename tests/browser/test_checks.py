"""Deterministic checks on the page: what a verification can, and cannot, count as proof."""

from plainproof.browser.playwright import PlaywrightBrowser

from .conftest import show


def ref_of(browser: PlaywrightBrowser, name: str) -> int:
    return next(e.ref for e in browser.observe().elements if e.name == name)


def test_text_found_with_its_context(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<p>Height: 330 metres</p>")
    found = browser.check_text("330 metres")
    assert found.ok
    assert found.message.startswith('CHECK OK: "330 metres" found in "...height: 330 metres')
    missing = browser.check_text("absent")
    assert not missing.ok
    assert missing.message == 'CHECK FAILED: "absent" not found in page'


def test_absence_checks(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<p>Hello</p>")
    assert browser.check_text("Error", absent=True).ok
    still = browser.check_text("Hello", absent=True)
    assert not still.ok
    assert "still present" in still.message


def test_url_checks(browser: PlaywrightBrowser) -> None:
    show(browser, "<h1>Orders</h1>")
    assert browser.check_url("PLAINPROOF.test").ok
    assert not browser.check_url("checkout").ok
    assert browser.check_url("checkout", absent=True).ok
    assert not browser.check_url("plainproof", absent=True).ok


def test_case_accents_and_accessibility_labels(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("<button aria-label='Profile of Jane DOE'>JD</button><p>Actualités</p>")
    assert browser.check_text("profile of jane").ok
    assert browser.check_text("actualites").ok


def test_iframes_are_read_but_hidden_ones_and_scripts_are_not(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        "<p>outer</p><iframe srcdoc='<p>inner text</p>'></iframe>"
        "<script>// signal an error</script><iframe style='display:none' srcdoc='<p>hidden Error</p>'></iframe>"
    )
    browser.page.wait_for_timeout(300)
    assert browser.check_text("inner text").ok
    assert browser.check_text("error", absent=True).ok


def test_a_text_typed_by_the_agent_is_no_proof(browser: PlaywrightBrowser) -> None:
    # Seen in a real run: the expected row did not exist, the agent typed its name into the
    # filter field, and the check found it... in that field.
    browser.page.set_content(
        '<label for="f">Filter</label><input id="f"><table><tr><td>Acme Corporation</td></tr></table>'
        '<label for="t">Title</label><input id="t" value="Spring sale">'
    )
    browser.type_text(ref_of(browser, "Filter"), "Globex")
    assert not browser.check_text("Globex").ok
    assert browser.only_in_typed_fields("Globex")
    assert browser.check_text("Spring sale").ok  # a value set by the application is a proof
    assert browser.check_text("Acme").ok


MENU = """
<nav>
  <button aria-expanded="false" aria-controls="team">Team</button>
  <ul id="team" style="display:none"><li><a href="#">Holidays of my team</a></li></ul>
  <details><summary>Settings</summary><a href="#">News block</a></details>
</nav>
"""


def test_a_folded_text_names_the_toggle_that_reveals_it(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(MENU)
    browser.observe()
    result = browser.check_text("Holidays of my team")
    assert not result.ok
    assert "hidden inside a collapsed section" in result.message
    assert '"Team"' in result.message
    assert '"Settings"' in browser.check_text("News block").message
    assert browser.check_text("Invoices").message == 'CHECK FAILED: "Invoices" not found in page'


TOAST = """
<div class="p-toast"></div>
<button onclick="toast('Files exported successfully')">Export</button><button>Other</button>
<script>
  function toast(msg) {
    const t = document.createElement('div'); t.className = 'p-toast-message'; t.textContent = msg;
    document.querySelector('.p-toast').appendChild(t);
    setTimeout(() => t.remove(), 300);
  }
</script>
"""


def test_a_toast_closed_before_the_check_still_counts(browser: PlaywrightBrowser) -> None:
    show(browser, TOAST)
    browser.click(ref_of(browser, "Export"))
    browser.page.wait_for_timeout(800)
    assert browser.page.locator(".p-toast-message").count() == 0
    result = browser.check_text("exported successfully")
    assert result.ok
    assert "temporary notification" in result.message


def test_a_toast_older_than_the_last_action_does_not_count(browser: PlaywrightBrowser) -> None:
    show(browser, TOAST)
    browser.click(ref_of(browser, "Export"))
    browser.page.wait_for_timeout(800)
    browser.click(ref_of(browser, "Other"))
    assert not browser.check_text("exported successfully").ok


def test_page_text_for_the_judge_includes_the_state_of_the_controls(browser: PlaywrightBrowser) -> None:
    browser.page.set_content("""
      <input type="checkbox" checked> checkbox 1<br>
      <input type="checkbox"> checkbox 2<br>
      <label for="dd">Dropdown List</label>
      <select id="dd"><option>Option 1</option><option selected>Option 2</option></select>
      <input type="text" aria-label="Comment" value="hello" disabled>
      <input type="password" aria-label="Password" value="hunter2">""")
    text = browser.page_text()
    assert 'checkbox "checkbox 1": checked' in text
    assert 'checkbox "checkbox 2": not checked' in text
    assert 'list "Dropdown List": shows "Option 2"' in text
    assert 'field "Comment": "hello" (disabled)' in text
    assert "hunter2" not in text


def test_disabled_buttons_are_stated_but_editor_toolbars_are_skipped(browser: PlaywrightBrowser) -> None:
    toolbar = '<div class="ql-toolbar">' + "<button disabled>Bold</button>" * 200 + "</div>"
    browser.page.set_content(toolbar + "<button disabled>Save</button><button>Cancel</button>")
    text = browser.page_text()
    assert 'button "Save": disabled' in text
    assert 'button "Bold"' not in text
    assert 'button "Cancel": disabled' not in text


def test_row_texts_tell_identical_buttons_apart(browser: PlaywrightBrowser) -> None:
    browser.page.set_content(
        "<table><tr><td>INV-1 01/12/2050</td><td><button>Delete</button></td></tr>"
        "<tr><td>INV-2 02/12/2050</td><td><button>Delete</button></td></tr></table><button>Outside</button>"
    )
    browser.observe()
    assert browser.row_texts() == {"1": "INV-1 01/12/2050 Delete", "2": "INV-2 02/12/2050 Delete"}


def test_hidden_fields_and_toggle_values_are_not_page_text(browser: PlaywrightBrowser) -> None:
    # A hidden input holds tokens the user never sees (they must not reach the judge), and the
    # value of a radio or checkbox is the meaningless "on".
    browser.page.set_content(
        "<form><input type='hidden' name='csrf' value='tok-9f8e7d'><label><input type='radio'> Plain box</label>"
        "<input type='submit' value='Send'><input aria-label='City' value='Paris'></form>"
    )
    text = browser.page_text()
    assert "tok-9f8e7d" not in text
    assert not browser.check_text("tok-9f8e7d").ok
    assert " on" not in text.split("[Form controls")[0]
    assert "Paris" in text
