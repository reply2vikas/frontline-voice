"""Accessibility gates enforced in CI.

Colour contrast is computed from the stylesheet rather than eyeballed, and the
markup is checked for the landmarks, labels and keyboard affordances that a
screen-reader user depends on.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")

AAA = 7.0


def _var(name: str) -> str:
    m = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS)
    assert m, f"--{name} not defined"
    return m.group(1)


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("fg", ["ink", "dim", "accent", "ok", "warn", "crit"])
@pytest.mark.parametrize("bg", ["bg", "panel", "panel2"])
def test_text_colours_meet_wcag_aaa(fg, bg):
    ratio = contrast(_var(fg), _var(bg))
    assert ratio >= AAA, f"--{fg} on --{bg} is {ratio:.2f}:1, below AAA {AAA}:1"


def test_skip_link_is_first_and_targets_main():
    assert HTML.index('class="skip"') < HTML.index("<header")
    assert 'href="#main"' in HTML
    assert 'id="main"' in HTML


def test_document_declares_language():
    assert '<html lang="en">' in HTML


def test_tabs_declare_full_aria_pattern():
    assert 'role="tablist"' in HTML
    assert HTML.count('role="tab"') == 3
    assert HTML.count('role="tabpanel"') == 3
    assert HTML.count("aria-controls") == 3
    assert HTML.count("aria-labelledby") == 3


def test_tabs_are_keyboard_navigable():
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in JS, f"{key} not handled"


def test_every_select_has_a_label():
    for select_id in re.findall(r'<select id="([^"]+)"', HTML):
        assert f'for="{select_id}"' in HTML


def test_focus_is_always_visible():
    assert ":focus-visible" in CSS
    assert "outline:none" not in CSS.replace(" ", "")


def test_touch_targets_meet_minimum_size():
    """Interactive controls must be at least 44px tall."""
    sizes = [int(m) for m in re.findall(r"min-height:(\d+)px", CSS)]
    assert sizes and all(s >= 44 for s in sizes)


def test_live_regions_present_for_async_updates():
    assert 'aria-live="polite"' in HTML
    assert 'role="status"' in HTML


def test_map_has_a_text_equivalent_table():
    assert 'id="zonetable"' in HTML
    assert "<caption>" in HTML


def test_svg_map_is_labelled_and_focusable():
    assert 'role="img"' in JS
    assert "aria-label" in JS
    assert 'tabindex="0"' in JS


def test_reduced_motion_is_respected():
    assert "prefers-reduced-motion" in CSS


def test_external_links_are_safe():
    assert 'rel="noopener noreferrer"' in JS
