"""Screenshots: numbered boxes for the model, the targeted element highlighted for humans."""

import io

from PIL import Image

from plainproof.browser.imaging import annotate, highlight_action
from plainproof.browser.model import Element

WHITE = (255, 255, 255)


def white_png(width: int = 200, height: int = 100) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def pixel(png: bytes, x: int, y: int) -> tuple[int, ...]:
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel((x, y))  # type: ignore[return-value]


def test_annotate_draws_a_numbered_box_and_keeps_the_size() -> None:
    button = Element(ref=1, tag="button", text="OK", box=(10.0, 30.0, 60.0, 60.0))
    out = annotate(white_png(), [button])
    assert Image.open(io.BytesIO(out)).size == (200, 100)
    assert pixel(out, 10, 45) != WHITE  # frame
    assert pixel(out, 12, 20) != WHITE  # number tag above the box


def test_annotate_skips_elements_outside_the_screenshot() -> None:
    below = Element(ref=2, tag="button", text="Far", box=(10.0, 30.0, 60.0, 60.0), on_screen=False)
    assert annotate(white_png(), [below]) == annotate(white_png(), [])


def test_highlight_draws_the_banner_and_a_cursor_on_the_target() -> None:
    button = Element(ref=1, tag="button", text="OK", box=(10.0, 50.0, 60.0, 90.0))
    out = highlight_action(white_png(), [button], 1, "CLICK [1]")
    assert pixel(out, 2, 2) != WHITE  # banner
    assert pixel(out, 35, 70) != WHITE  # cursor


def test_highlight_without_target_only_draws_the_banner() -> None:
    out = highlight_action(white_png(), [], None, "PRESS Enter")
    assert pixel(out, 2, 2) != WHITE
    assert pixel(out, 150, 80) == WHITE
