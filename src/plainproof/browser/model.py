"""What the model sees of a page: numbered interactive elements, with their state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


def _box(value: Any) -> tuple[float, float, float, float]:
    try:
        left, top, right, bottom = (float(v) for v in value)
    except (TypeError, ValueError):
        return 0.0, 0.0, 0.0, 0.0
    return left, top, right, bottom


@dataclass(frozen=True)
class Element:
    """An interactive element, numbered on the screenshot (Set-of-Marks)."""

    ref: int
    tag: str
    type: str = ""
    role: str = ""
    text: str = ""
    label: str = ""
    href: str = ""
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    """Left, top, right, bottom in viewport pixels (clipped to the viewport)."""
    options: tuple[str, ...] = ()
    value: str = ""
    """Current value of a text field."""
    checked: bool | None = None
    """State of a checkbox or radio button."""
    expanded: str = ""
    """``aria-expanded`` of menus and dropdown triggers: "true", "false" or ""."""
    kind: str = ""
    """"date", "checkbox", "radio" or ""."""
    off: str = ""
    """"above" or "below" when the element is outside the current viewport."""
    on_screen: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))
        object.__setattr__(self, "box", tuple(self.box))

    @classmethod
    def from_js(cls, data: Mapping[str, Any]) -> Element:
        return cls(
            ref=int(data["ref"]),
            tag=str(data.get("tag", "")),
            type=str(data.get("type", "")),
            role=str(data.get("role", "")),
            text=str(data.get("text", "")),
            label=str(data.get("label", "")),
            href=str(data.get("href", "")),
            box=_box(data.get("box")),
            options=tuple(data.get("options") or ()),
            value=str(data.get("value", "")),
            checked=data.get("checked"),
            expanded=str(data.get("expanded", "")),
            kind=str(data.get("kind", "")),
            off=str(data.get("off", "")),
            on_screen=bool(data.get("onScreen", True)),
        )

    @property
    def name(self) -> str:
        """What a human would call it: its label, else its text."""
        return self.label or self.text

    def describe(self) -> str:
        parts = [f"[{self.ref}] <{self.tag}"]
        if self.type:
            parts.append(f' type="{self.type}"')
        if self.role:
            parts.append(f' role="{self.role}"')
        parts.append(">")
        if self.label:
            parts.append(f' label="{self.label}"')
        if self.text:
            parts.append(f' text="{self.text}"')
        if self.value:
            parts.append(f' value="{self.value}"')
        if self.checked is not None:
            parts.append(" checked" if self.checked else " unchecked")
        if self.expanded:
            parts.append(f" expanded={self.expanded}")
        if self.kind == "date":
            parts.append(" [date field: use type, the calendar closes by itself]")
        if self.href:
            parts.append(f" href={self.href}")
        if self.options:
            parts.append(" options=[" + ", ".join(repr(o) for o in self.options) + "]")
        if self.off:
            parts.append(f" ({self.off} the current view, it will be scrolled to automatically)")
        return "".join(parts)


@dataclass
class Observation:
    url: str
    title: str
    elements: list[Element] = field(default_factory=list)
    screenshot_png: bytes = b""
    annotated_png: bytes = b""
    truncated: int = 0
    """Elements left out because the page has too many of them."""

    def elements_text(self) -> str:
        if not self.elements:
            return "(no visible interactive element)"
        lines = [e.describe() for e in self.elements]
        if self.truncated:
            lines.append(f"({self.truncated} more elements further down the page: scroll to reach them)")
        return "\n".join(lines)

    def by_ref(self, ref: int | None) -> Element | None:
        return next((e for e in self.elements if e.ref == ref), None)


@dataclass(frozen=True)
class CheckResult:
    """A deterministic verification made on the page itself."""

    ok: bool
    message: str

    @classmethod
    def passed(cls, detail: str) -> CheckResult:
        return cls(True, f"CHECK OK: {detail}")

    @classmethod
    def failed(cls, detail: str) -> CheckResult:
        return cls(False, f"CHECK FAILED: {detail}")

    def __str__(self) -> str:
        return self.message
