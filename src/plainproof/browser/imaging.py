"""Screenshots drawn for the model (numbered boxes) and for humans (the action performed)."""

from __future__ import annotations

import functools
import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from .model import Element

_FONT_CANDIDATES = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
)

MARK_COLOR = (220, 38, 38)
ACTION_COLOR = (21, 128, 61)

FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont


@functools.cache
def _font(size: int) -> FontType:
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def annotate(png: bytes, elements: Sequence[Element]) -> bytes:
    """A frame and a number on every interactive element visible in the screenshot."""
    image = Image.open(io.BytesIO(png)).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _font(13)
    for element in elements:
        if not element.on_screen:  # listed for the model, but outside the captured image
            continue
        x0, y0, x1, y1 = element.box
        draw.rectangle((x0, y0, x1, y1), outline=MARK_COLOR, width=2)
        label = str(element.ref)
        width = draw.textlength(label, font=font)
        top = max(y0 - 17, 0)
        draw.rectangle((x0, top, x0 + width + 6, top + 17), fill=MARK_COLOR)
        draw.text((x0 + 3, top + 1), label, fill="white", font=font)
    return _png(image)


def highlight_action(png: bytes, elements: Sequence[Element], ref: int | None, banner: str) -> bytes:
    """What the agent did: a banner describing the action and, when an element is targeted,
    a thick frame and a cursor on it (drawn on the raw screenshot)."""
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    color = (*ACTION_COLOR, 255)
    target = next((e for e in elements if e.ref == ref), None) if ref is not None else None
    if target is not None and target.on_screen:
        x0, y0, x1, y1 = target.box
        draw.rectangle((x0 - 3, y0 - 3, x1 + 3, y1 + 3), outline=color, width=4)
        draw.rectangle((x0, y0, x1, y1), fill=(*ACTION_COLOR, 40))
        cx, cy, radius = (x0 + x1) / 2, (y0 + y1) / 2, 9
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 255, 255, 230), outline=color, width=3
        )
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=color)
    font = _font(15)
    pad = 8
    width = draw.textlength(banner, font=font)
    draw.rectangle((0, 0, width + 2 * pad, 18 + 2 * pad), fill=(*ACTION_COLOR, 235))
    draw.text((pad, pad), banner, fill="white", font=font)
    return _png(Image.alpha_composite(image, overlay).convert("RGB"))
